<script setup lang="ts">
import { PhXCircle, PhPencilSimple, PhCheck, PhX, PhArrowSquareOut, PhArrowCounterClockwise } from '@phosphor-icons/vue'
import { computed, watch, nextTick, ref, onBeforeUnmount } from 'vue'
import type { Task, MarkdownHeadingItem } from '../types'
import { TaskStatus } from '../types'
import { Incremark } from '@incremark/vue'
import { marked } from 'marked'
import TaskMetaCard from './TaskMetaCard.vue'
import { countWords, stripDoubleBracePlaceholders } from '../utils/formatters'
import { postProcessCompiledMarkdown } from '../utils/markdownPostProcessor'
import { normalizeAccidentalInlineCodeBlocks } from '../utils/markdownNormalizer'
import { normalizeMermaidSvgLayout } from '../utils/mermaidLayout'
import { useMarkdownTheme } from '../composables/useMarkdownTheme'
import { getMermaid } from '../utils/mermaidLoader'

interface SummaryHighlightRequest {
  taskId: string
  keyword: string
  source: 'topic' | 'summary'
  requestId: number
}

interface Props {
  task: Task
  activeTab: 'summary' | 'transcript'
  compiledMarkdown: string
  summaryHighlightRequest?: SummaryHighlightRequest | null
  headingJumpRequest?: { id: string; requestId: number } | null
  topic: string
  isEditingTopic: boolean
  editingTopicValue: string
  isEditingSummary: boolean
  editingSummaryValue: string
  isSavingSummary: boolean
  isStreamingSummary: boolean
  streamingBlocks: any[]
  compiledResumeSummary: string
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'open-mermaid-viewer': [target: HTMLElement]
  'start-edit-topic': []
  'save-topic': []
  'cancel-edit-topic': []
  'update:editing-topic-value': [value: string]
  'start-edit-summary': []
  'save-summary': []
  'cancel-edit-summary': []
  'update:editing-summary-value': [value: string]
  'open-local': []
  'reload-local': []
  'update-markdown-headings': [headings: MarkdownHeadingItem[]]
  'update-active-heading-id': [headingId: string]
}>()

const isCompleted = computed(() => props.task.status === TaskStatus.COMPLETED)
const isFailed = computed(() => props.task.status === TaskStatus.FAILED)
const isLoading = computed(() => !isCompleted.value && !isFailed.value)
const contentScrollRef = ref<HTMLElement | null>(null)
const summaryArticleRef = ref<HTMLElement | null>(null)
const summaryEditorRef = ref<HTMLTextAreaElement | null>(null)
const SUMMARY_HIGHLIGHT_CLASS = 'summary-search-highlight'
const mermaidRenderVersion = ref(0)
const markdownHeadings = ref<MarkdownHeadingItem[]>([])
const activeHeadingId = ref('')
let headingObserver: IntersectionObserver | null = null
const headingElementMap = new Map<string, HTMLElement>()

// 使用主题管理 Hook（仅用于状态追踪，样式通过 CSS 自动应用）
const { currentThemeId } = useMarkdownTheme()

const summaryWordCount = computed(() => {
  if (!props.task.summary) return 0
  return countWords(props.task.summary)
})

// 双栏编辑模式的实时预览（基于编辑中的内容渲染，未保存不影响正式展示）
const editingPreviewHtml = computed(() => {
  if (!props.editingSummaryValue) return ''
  const cleaned = stripDoubleBracePlaceholders(props.editingSummaryValue)
  const html = marked.parse(cleaned) as string
  return postProcessCompiledMarkdown(html, {
    videoUrl: props.task.video_url || '',
  })
})

const showContent = computed(() => {
  if (props.activeTab === 'summary') {
    return !!props.task.summary
  }
  return !!props.task.transcript
})

const cleanupHeadingObserver = () => {
  if (headingObserver) {
    headingObserver.disconnect()
    headingObserver = null
  }
}

const clearMarkdownHeadings = () => {
  cleanupHeadingObserver()
  markdownHeadings.value = []
  activeHeadingId.value = ''
  headingElementMap.clear()
  emit('update-markdown-headings', [])
  emit('update-active-heading-id', '')
}

const slugifyHeading = (text: string) => {
  return text
    .toLowerCase()
    .trim()
    .replace(/\s+/g, '-')
    .replace(/[^\w\u4e00-\u9fa5-]/g, '')
    .replace(/-+/g, '-')
    .replace(/^-+|-+$/g, '')
}

const setupHeadingObserver = () => {
  cleanupHeadingObserver()
  const container = contentScrollRef.value
  if (!container || headingElementMap.size === 0) return

  const observedHeadings = Array.from(headingElementMap.values())
  headingObserver = new IntersectionObserver(
    (entries) => {
      const visibleEntries = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)

      const firstVisible = visibleEntries[0]
      if (firstVisible) {
        activeHeadingId.value = (firstVisible.target as HTMLElement).id
        return
      }

      const containerTop = container.getBoundingClientRect().top + 96
      let nearestId = ''
      let nearestOffset = Number.POSITIVE_INFINITY
      observedHeadings.forEach((element) => {
        const offset = Math.abs(element.getBoundingClientRect().top - containerTop)
        if (offset < nearestOffset) {
          nearestId = element.id
          nearestOffset = offset
        }
      })
      if (nearestId) {
        activeHeadingId.value = nearestId
      }
    },
    {
      root: container,
      rootMargin: '-96px 0px -60% 0px',
      threshold: [0, 1],
    },
  )

  observedHeadings.forEach((element) => headingObserver?.observe(element))
}

const collectMarkdownHeadings = async () => {
  await nextTick()
  const contentRoot = summaryArticleRef.value?.querySelector('[data-summary-content]') as HTMLElement | null
  if (!contentRoot) {
    clearMarkdownHeadings()
    return
  }

  const headingElements = Array.from(contentRoot.querySelectorAll('h1, h2, h3, h4')) as HTMLElement[]
  if (!headingElements.length) {
    clearMarkdownHeadings()
    return
  }

  const slugCounter = new Map<string, number>()
  const collected: MarkdownHeadingItem[] = []
  headingElementMap.clear()

  headingElements.forEach((element, index) => {
    const text = (element.textContent || '').trim()
    if (!text) return

    const level = Number(element.tagName.replace('H', '')) || 2
    const baseSlug = slugifyHeading(text) || `section-${index + 1}`
    const currentCount = slugCounter.get(baseSlug) || 0
    slugCounter.set(baseSlug, currentCount + 1)
    const uniqueSlug = currentCount === 0 ? baseSlug : `${baseSlug}-${currentCount + 1}`

    element.id = uniqueSlug
    collected.push({
      id: uniqueSlug,
      text,
      level,
    })
    headingElementMap.set(uniqueSlug, element)
  })

  markdownHeadings.value = collected
  activeHeadingId.value = collected[0]?.id || ''
  emit('update-markdown-headings', collected)
  emit('update-active-heading-id', activeHeadingId.value)
  setupHeadingObserver()
}

const jumpToHeading = (headingId: string) => {
  const container = contentScrollRef.value
  const target = headingElementMap.get(headingId)
  if (!container || !target) return

  const containerRect = container.getBoundingClientRect()
  const targetRect = target.getBoundingClientRect()
  const offsetTop = targetRect.top - containerRect.top + container.scrollTop - 88

  container.scrollTo({
    top: Math.max(0, offsetTop),
    behavior: 'smooth',
  })
  // 不立即更新 activeHeadingId，让 IntersectionObserver 自然更新
}

const clearSummaryHighlight = () => {
  if (!summaryArticleRef.value) return
  const marks = summaryArticleRef.value.querySelectorAll(`mark.${SUMMARY_HIGHLIGHT_CLASS}`)
  marks.forEach((mark) => {
    const parent = mark.parentNode
    if (!parent) return
    parent.replaceChild(document.createTextNode(mark.textContent || ''), mark)
    parent.normalize()
  })
}

const findAndHighlightInSummary = (root: HTMLElement, keyword: string): HTMLElement | null => {
  const trimmedKeyword = keyword.trim()
  if (!trimmedKeyword) return null
  const lowerKeyword = trimmedKeyword.toLowerCase()

  const walker = document.createTreeWalker(
    root,
    NodeFilter.SHOW_TEXT,
    {
      acceptNode: (node: Node) => {
        const text = node.textContent || ''
        if (!text.trim()) return NodeFilter.FILTER_REJECT
        const parent = (node as Text).parentElement
        if (!parent) return NodeFilter.FILTER_REJECT
        if (parent.closest(`mark.${SUMMARY_HIGHLIGHT_CLASS}`)) return NodeFilter.FILTER_REJECT
        if (parent.closest('pre, code, .mermaid, svg, script, style')) return NodeFilter.FILTER_REJECT
        return NodeFilter.FILTER_ACCEPT
      },
    },
  )

  let currentNode = walker.nextNode() as Text | null
  while (currentNode) {
    const lowerText = currentNode.data.toLowerCase()
    const matchIndex = lowerText.indexOf(lowerKeyword)
    if (matchIndex >= 0) {
      const matchedTextNode = currentNode.splitText(matchIndex)
      matchedTextNode.splitText(trimmedKeyword.length)

      const mark = document.createElement('mark')
      mark.className = SUMMARY_HIGHLIGHT_CLASS
      mark.textContent = matchedTextNode.data
      matchedTextNode.parentNode?.replaceChild(mark, matchedTextNode)
      return mark
    }
    currentNode = walker.nextNode() as Text | null
  }

  return null
}

const applySummaryHighlight = async () => {
  const request = props.summaryHighlightRequest
  if (!request || request.taskId !== props.task.id || props.activeTab !== 'summary') {
    clearSummaryHighlight()
    return
  }

  const keyword = request.keyword.trim()
  if (!keyword) {
    clearSummaryHighlight()
    return
  }

  await nextTick()
  const contentRoot = summaryArticleRef.value?.querySelector('[data-summary-content]') as HTMLElement | null
  if (!contentRoot) return

  clearSummaryHighlight()
  const highlighted = findAndHighlightInSummary(contentRoot, keyword)
  if (highlighted) {
    highlighted.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
}

const MERMAID_ICON_DOWNLOAD = 'M224,144v64a8,8,0,0,1-8,8H40a8,8,0,0,1-8-8V144a8,8,0,0,1,16,0v56H208V144a8,8,0,0,1,16,0Zm-101.66,5.66a8,8,0,0,0,11.32,0l40-40a8,8,0,0,0-11.32-11.32L136,124.69V32a8,8,0,0,0-16,0v92.69L93.66,98.34a8,8,0,0,0-11.32,11.32Z'
const MERMAID_ICON_COPY = 'M216,32H88a8,8,0,0,0-8,8V80H40a8,8,0,0,0-8,8V216a8,8,0,0,0,8,8H168a8,8,0,0,0,8-8V176h40a8,8,0,0,0,8-8V40A8,8,0,0,0,216,32ZM160,208H48V96H160Zm48-48H176V88a8,8,0,0,0-8-8H96V48H208Z'
const MERMAID_ICON_CODE = 'M69.12,94.15,28.5,128l40.62,33.85a8,8,0,1,1-10.24,12.29l-48-40a8,8,0,0,1,0-12.29l48-40a8,8,0,0,1,10.24,12.3Zm176,27.7-48-40a8,8,0,1,0-10.24,12.3L227.5,128l-40.62,33.85a8,8,0,1,0,10.24,12.29l48-40a8,8,0,0,0,0-12.29ZM162.73,32.48a8,8,0,0,0-10.25,4.79l-64,176a8,8,0,0,0,4.79,10.26A8.14,8.14,0,0,0,96,224a8,8,0,0,0,7.52-5.27l64-176A8,8,0,0,0,162.73,32.48Z'
const MERMAID_ICON_PREVIEW = 'M216,48V96a8,8,0,0,1-16,0V67.31l-42.34,42.35a8,8,0,0,1-11.32-11.32L188.69,56H160a8,8,0,0,1,0-16h48A8,8,0,0,1,216,48ZM98.34,146.34,56,188.69V160a8,8,0,0,0-16,0v48a8,8,0,0,0,8,8H96a8,8,0,0,0,0-16H67.31l42.35-42.34a8,8,0,0,0-11.32-11.32ZM208,152a8,8,0,0,0-8,8v28.69l-42.34-42.35a8,8,0,0,0-11.32,11.32L188.69,200H160a8,8,0,0,0,0,16h48a8,8,0,0,0,8-8V160A8,8,0,0,0,208,152ZM67.31,56H96a8,8,0,0,0,0-16H48a8,8,0,0,0-8,8V96a8,8,0,0,0,16,0V67.31l42.34,42.35a8,8,0,0,0,11.32-11.32Z'

const createMermaidToolButton = (title: string, iconPath: string) => {
  const button = document.createElement('button')
  button.type = 'button'
  button.className = 'ss-mermaid-tool-btn'
  button.title = title
  button.setAttribute('aria-label', title)

  const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  icon.setAttribute('viewBox', '0 0 256 256')
  icon.setAttribute('aria-hidden', 'true')
  icon.classList.add('ss-mermaid-tool-icon')
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path')
  path.setAttribute('d', iconPath)
  icon.appendChild(path)
  button.appendChild(icon)

  return button
}

const copyTextToClipboard = async (text: string): Promise<boolean> => {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // Fallback to execCommand below.
  }

  try {
    const textArea = document.createElement('textarea')
    textArea.value = text
    textArea.setAttribute('readonly', '')
    textArea.style.position = 'fixed'
    textArea.style.opacity = '0'
    textArea.style.pointerEvents = 'none'
    document.body.appendChild(textArea)
    textArea.select()
    const copied = document.execCommand('copy')
    textArea.remove()
    return copied
  } catch {
    return false
  }
}

const renderMermaidBlocks = async () => {
  const renderVersion = ++mermaidRenderVersion.value
  const contentRoot = summaryArticleRef.value?.querySelector('[data-summary-content]') as HTMLElement | null
  if (!contentRoot) return

  normalizeAccidentalInlineCodeBlocks(contentRoot)

  const mermaidNodes = Array.from(contentRoot.querySelectorAll('.mermaid')) as HTMLElement[]
  if (!mermaidNodes.length) return

  for (const [index, sourceNode] of mermaidNodes.entries()) {
    if (renderVersion !== mermaidRenderVersion.value) return

    const code = (sourceNode.textContent || '').trim()
    const block = document.createElement('div')
    block.className = 'ss-mermaid-block'

    const diagramWrap = document.createElement('div')
    diagramWrap.className = 'ss-mermaid-diagram-wrap'

    const toolbar = document.createElement('div')
    toolbar.className = 'ss-mermaid-toolbar'

    const downloadSvgButton = createMermaidToolButton('下载 SVG', MERMAID_ICON_DOWNLOAD)
    downloadSvgButton.disabled = true

    const copyCodeButton = createMermaidToolButton('复制代码', MERMAID_ICON_COPY)
    copyCodeButton.disabled = !code

    const toggleCodeButton = createMermaidToolButton('查看代码', MERMAID_ICON_CODE)

    const previewButton = createMermaidToolButton('预览', MERMAID_ICON_PREVIEW)
    previewButton.disabled = true

    const renderHost = document.createElement('div')
    renderHost.className = 'ss-mermaid-render'

    const codePanel = document.createElement('pre')
    codePanel.className = 'ss-mermaid-code-panel'
    codePanel.hidden = true
    const codeElement = document.createElement('code')
    codeElement.className = 'language-mermaid'
    codeElement.textContent = code
    codePanel.appendChild(codeElement)

    toolbar.appendChild(downloadSvgButton)
    toolbar.appendChild(copyCodeButton)
    toolbar.appendChild(toggleCodeButton)
    toolbar.appendChild(previewButton)
    diagramWrap.appendChild(toolbar)
    diagramWrap.appendChild(renderHost)
    block.appendChild(diagramWrap)
    block.appendChild(codePanel)

    sourceNode.replaceWith(block)

    const toggleCode = () => {
      const isHidden = codePanel.hidden
      codePanel.hidden = !isHidden
      toggleCodeButton.classList.toggle('active', isHidden)
    }
    toggleCodeButton.addEventListener('click', toggleCode)

    downloadSvgButton.addEventListener('click', () => {
      const svg = renderHost.querySelector('svg')
      if (!svg) return

      const svgClone = svg.cloneNode(true) as SVGElement
      if (!svgClone.getAttribute('xmlns')) {
        svgClone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
      }
      if (!svgClone.getAttribute('xmlns:xlink')) {
        svgClone.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink')
      }

      const serialized = new XMLSerializer().serializeToString(svgClone)
      const blob = new Blob([serialized], { type: 'image/svg+xml;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `mermaid-${props.task.id}-${index + 1}.svg`
      document.body.appendChild(link)
      link.click()
      link.remove()
      setTimeout(() => URL.revokeObjectURL(url), 0)
    })

    copyCodeButton.addEventListener('click', async () => {
      if (!code) return
      const copied = await copyTextToClipboard(code)
      copyCodeButton.classList.toggle('active', copied)
      copyCodeButton.title = copied ? '已复制代码' : '复制失败'
      setTimeout(() => {
        copyCodeButton.classList.remove('active')
        copyCodeButton.title = '复制代码'
      }, 1200)
    })

    previewButton.addEventListener('click', () => {
      if (!renderHost.querySelector('svg')) return
      emit('open-mermaid-viewer', renderHost)
    })

    try {
      if (!code) {
        throw new Error('未检测到 Mermaid 代码块内容。')
      }
      const mermaid = await getMermaid()
      const renderId = `ss-mermaid-${props.task.id}-${renderVersion}-${index}`
      const result = await mermaid.render(renderId, code)
      if (renderVersion !== mermaidRenderVersion.value) return

      renderHost.innerHTML = result.svg
      result.bindFunctions?.(renderHost)
      normalizeMermaidSvgLayout(renderHost)
      requestAnimationFrame(() => normalizeMermaidSvgLayout(renderHost))
      downloadSvgButton.disabled = false
      previewButton.disabled = false
    } catch (error) {
      if (renderVersion !== mermaidRenderVersion.value) return
      // 渲染失败时直接移除整个 mermaid 块，不显示错误信息
      block.remove()
    }
  }
}

// 监听内容变化并渲染 Mermaid
watch([() => props.compiledMarkdown, () => props.activeTab, () => props.isStreamingSummary], async () => {
  if (props.activeTab === 'summary' && props.compiledMarkdown && !props.isStreamingSummary) {
    await nextTick()
    try {
      await renderMermaidBlocks()
    } catch (e) {
      console.error('Mermaid render failed:', e)
    }
    await collectMarkdownHeadings()
    return
  }

  clearMarkdownHeadings()
}, { immediate: true })

watch(
  [
    () => props.summaryHighlightRequest?.requestId,
    () => props.summaryHighlightRequest?.taskId,
    () => props.summaryHighlightRequest?.keyword,
    () => props.task.id,
    () => props.compiledMarkdown,
    () => props.activeTab,
  ],
  async () => {
    await applySummaryHighlight()
  },
  { immediate: true },
)

watch(
  () => activeHeadingId.value,
  (headingId) => {
    emit('update-active-heading-id', headingId)
  },
)

watch(
  () => props.headingJumpRequest?.requestId,
  () => {
    if (props.activeTab !== 'summary') return
    const headingId = props.headingJumpRequest?.id
    if (!headingId) return
    jumpToHeading(headingId)
  },
)

onBeforeUnmount(() => {
  clearMarkdownHeadings()
})

watch(() => props.streamingBlocks, () => {
  if (!props.isStreamingSummary) return
  nextTick(() => {
    const container = contentScrollRef.value
    if (!container) return
    const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight
    if (distanceFromBottom < 150) {
      container.scrollTop = container.scrollHeight
    }
  })
})

// 进入编辑模式时自动聚焦编辑器
watch(
  () => props.isEditingSummary,
  (editing) => {
    if (editing) {
      nextTick(() => {
        summaryEditorRef.value?.focus()
      })
    }
  },
)
</script>

<template>
  <div ref="contentScrollRef" class="flex-1 overflow-y-auto overflow-x-auto p-4 md:p-8 pt-16 md:pt-20 custom-scrollbar">
    <div class="max-w-4xl mx-auto">
      <!-- 错误状态 -->
      <div v-if="isFailed" class="bg-red-50 border border-red-100 p-6 rounded-2xl mb-6">
        <div class="flex items-center gap-3 text-red-700 font-bold mb-2">
          <PhXCircle :size="24" />
          处理失败
        </div>
        <p class="text-red-600 text-sm">{{ task.error_message || '未知错误' }}</p>
      </div>

      <!-- 加载状态 -->
      <div v-else-if="isLoading && !showContent" class="flex flex-col items-center justify-center h-full pt-20">
        <div class="w-14 h-14 border-4 border-blue-100 border-t-blue-500 rounded-full animate-spin mb-6"></div>
        <h3 class="text-lg font-medium text-slate-700">正在处理中...</h3>
        <p class="text-slate-400 mt-2">这通常需要几分钟，请稍候</p>
      </div>

      <!-- 成功内容区 -->
      <div v-else class="bg-white rounded-2xl shadow-sm border border-slate-200 min-h-[500px] relative">
        <!-- AI 总结 Tab -->
        <div v-show="activeTab === 'summary'">
          <!-- 顶部元信息卡片 -->
          <div class="px-8 pt-8 pb-6 border-b border-slate-200">
            <div class="flex items-start justify-between gap-4">
              <TaskMetaCard
                :task="task"
                :topic="topic"
                :summary-word-count="summaryWordCount"
                :is-editing-topic="isEditingTopic"
                :editing-topic-value="editingTopicValue"
                @start-edit-topic="emit('start-edit-topic')"
                @save-topic="emit('save-topic')"
                @cancel-edit-topic="emit('cancel-edit-topic')"
                @update:editing-topic-value="(val) => emit('update:editing-topic-value', val)"
              />
              <div
                v-if="isCompleted && task.summary && !isEditingSummary && !isStreamingSummary"
                class="flex items-center gap-2 shrink-0"
              >
                <button
                  @click="emit('open-local')"
                  class="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-gray-200 bg-white text-slate-500 hover:text-primary hover:border-blue-200 hover:bg-blue-50 transition-colors text-xs"
                  title="在本地默认编辑器（如 Typora、VS Code）中打开总结文件"
                >
                  <PhArrowSquareOut :size="14" />
                  <span>本地打开</span>
                </button>
                <button
                  @click="emit('reload-local')"
                  class="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-gray-200 bg-white text-slate-500 hover:text-primary hover:border-blue-200 hover:bg-blue-50 transition-colors text-xs"
                  title="读取本地修改后的文件并同步回网页"
                >
                  <PhArrowCounterClockwise :size="14" />
                  <span>重新载入</span>
                </button>
                <button
                  @click="emit('start-edit-summary')"
                  class="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-gray-200 bg-white text-slate-500 hover:text-primary hover:border-blue-200 hover:bg-blue-50 transition-colors text-xs"
                  title="编辑总结内容（Markdown）"
                >
                  <PhPencilSimple :size="14" />
                  <span>编辑总结</span>
                </button>
              </div>
            </div>
          </div>

          <!-- 编辑总结模式（双栏：源码 + 实时预览） -->
          <div v-if="isEditingSummary" class="px-8 py-6">
            <div class="flex items-center justify-between mb-3">
              <h3 class="text-sm font-semibold text-slate-600">编辑总结内容</h3>
              <div class="flex items-center gap-2">
                <button
                  @click="emit('open-local')"
                  class="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-slate-200 text-slate-500 hover:bg-blue-50 hover:text-primary hover:border-blue-200 transition-colors text-sm"
                  title="在本地默认编辑器（如 Typora、VS Code）中打开总结文件"
                >
                  <PhArrowSquareOut :size="16" />
                  本地打开
                </button>
                <button
                  @click="emit('reload-local')"
                  class="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-slate-200 text-slate-500 hover:bg-blue-50 hover:text-primary hover:border-blue-200 transition-colors text-sm"
                  title="读取本地修改后的文件并同步回编辑框与网页"
                >
                  <PhArrowCounterClockwise :size="16" />
                  重新载入
                </button>
                <button
                  @click="emit('cancel-edit-summary')"
                  class="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 transition-colors text-sm"
                >
                  <PhX :size="16" />
                  取消
                </button>
                <button
                  @click="emit('save-summary')"
                  :disabled="isSavingSummary"
                  class="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 transition-colors text-sm font-medium"
                >
                  <PhCheck :size="16" />
                  {{ isSavingSummary ? '保存中...' : '保存' }}
                </button>
              </div>
            </div>
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <!-- 左栏：Markdown 源码编辑 -->
              <div class="flex flex-col rounded-xl border border-slate-200 overflow-hidden min-h-[60vh]">
                <div class="px-3 py-2 bg-slate-100 border-b border-slate-200 text-xs font-medium text-slate-500">
                  Markdown 源码
                </div>
                <textarea
                  ref="summaryEditorRef"
                  :value="editingSummaryValue"
                  @input="emit('update:editing-summary-value', ($event.target as HTMLTextAreaElement).value)"
                  class="flex-1 w-full min-h-[55vh] p-4 outline-none font-mono text-sm leading-relaxed bg-white custom-scrollbar resize-none"
                  placeholder="在此编辑总结内容..."
                ></textarea>
              </div>
              <!-- 右栏：实时预览 -->
              <div class="flex flex-col rounded-xl border border-slate-200 overflow-hidden min-h-[60vh]">
                <div class="px-3 py-2 bg-slate-100 border-b border-slate-200 text-xs font-medium text-slate-500">
                  实时预览
                </div>
                <div class="flex-1 overflow-y-auto p-4 custom-scrollbar">
                  <div
                    v-if="editingPreviewHtml"
                    class="prose prose-sm md:prose-base prose-slate prose-headings:font-bold prose-a:text-blue-600 hover:prose-a:underline prose-img:rounded-xl max-w-none ss-shared-prose markdown-theme-container"
                    :data-theme="currentThemeId"
                    v-html="editingPreviewHtml"
                  ></div>
                  <p v-else class="text-slate-400 italic text-sm">预览为空</p>
                </div>
              </div>
            </div>
          </div>

          <!-- 总结内容 - 添加主题容器类 -->
          <article
            v-else
            ref="summaryArticleRef"
            class="prose prose-sm md:prose-base prose-slate prose-headings:font-bold prose-a:text-blue-600 hover:prose-a:underline prose-img:rounded-xl max-w-none px-8 py-8 ss-shared-prose markdown-theme-container"
            :data-theme="currentThemeId"
          >
            <!-- 快照模式：切回来时有已有内容 + 新 delta 增量 -->
            <template v-if="compiledResumeSummary">
              <div data-summary-content v-html="compiledResumeSummary"></div>
              <div v-if="isStreamingSummary && streamingBlocks.length" data-summary-content class="ss-streaming-content">
                <Incremark :blocks="streamingBlocks" />
              </div>
            </template>
            <!-- 普通模式 -->
            <template v-else>
              <div v-if="isStreamingSummary && streamingBlocks.length" data-summary-content class="ss-streaming-content">
                <Incremark :blocks="streamingBlocks" />
              </div>
              <div v-else-if="task.summary" data-summary-content v-html="compiledMarkdown"></div>
              <p v-else class="text-slate-400 italic">暂无总结内容</p>
            </template>
          </article>
        </div>

        <!-- 转录文本 Tab -->
        <div v-show="activeTab === 'transcript'" class="px-8 py-8">
          <div class="flex justify-between items-center mb-6">
            <h3 class="text-lg font-bold text-slate-800">全文转录</h3>
          </div>
          <div class="space-y-4 text-slate-600 leading-relaxed font-normal">
            <p v-if="task.transcript" class="whitespace-pre-wrap text-sm leading-relaxed">{{ task.transcript }}</p>
            <p v-else class="text-gray-400 italic">暂无转录内容</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style>
/* ========== 自定义滚动条样式 ========== */
.custom-scrollbar::-webkit-scrollbar {
  width: 8px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: #d1d5db;
  border-radius: 4px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: #9ca3af;
}

/* ========== Tailwind Typography (prose) 样式微调 ========== */
/* 注意：大部分样式已移至 styles/markdown-themes/base.css */
/* 这里只保留不在主题系统中的样式 */

/* ========== Mermaid 渲染容器样式 ========== */
.ss-mermaid-block {
  margin: 1.5rem 0;
  max-width: 100%;
  min-width: 0;
}

.ss-mermaid-diagram-wrap {
  position: relative;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 1rem;
  transition: border-color 0.2s, box-shadow 0.2s;
  max-width: 100%;
  overflow: visible;
}

.ss-mermaid-diagram-wrap:hover {
  border-color: #94a3b8;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}

.ss-mermaid-toolbar {
  position: absolute;
  top: 0.55rem;
  right: 0.55rem;
  z-index: 2;
  display: flex;
  gap: 0.4rem;
  opacity: 0;
  pointer-events: none;
  transform: translateY(-2px);
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.ss-mermaid-diagram-wrap:hover .ss-mermaid-toolbar,
.ss-mermaid-diagram-wrap:focus-within .ss-mermaid-toolbar {
  opacity: 1;
  pointer-events: auto;
  transform: translateY(0);
}

.ss-mermaid-tool-btn {
  border: 1px solid #cbd5e1;
  background: rgba(255, 255, 255, 0.9);
  color: #334155;
  border-radius: 999px;
  width: 1.95rem;
  height: 1.95rem;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background-color 0.15s, border-color 0.15s, color 0.15s;
}

.ss-mermaid-tool-icon {
  width: 0.95rem;
  height: 0.95rem;
  fill: currentColor;
}

.ss-mermaid-tool-btn:hover {
  background: #eff6ff;
  border-color: #60a5fa;
  color: #1d4ed8;
}

.ss-mermaid-tool-btn.active {
  background: #dbeafe;
  border-color: #3b82f6;
  color: #1d4ed8;
}

.ss-mermaid-tool-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.ss-mermaid-render {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 140px;
  max-width: 100%;
  min-width: 0;
  overflow: auto;
}

.ss-mermaid-render svg {
  max-width: 100%;
  height: auto;
  display: block;
  margin-left: auto;
  margin-right: auto;
  flex-shrink: 0;
}

.ss-mermaid-code-panel {
  margin-top: 0.55rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 0.8rem;
  overflow-x: auto;
}

.ss-mermaid-code-panel code {
  color: #334155;
  font-size: 0.8rem;
}

.ss-mermaid-error {
  width: 100%;
  max-width: 100%;
  border: 1px solid #fca5a5;
  border-radius: 8px;
  background: #fff1f2;
  color: #991b1b;
  padding: 0.8rem;
  overflow: hidden;
  box-sizing: border-box;
}

.ss-mermaid-error-title {
  font-size: 0.82rem;
  font-weight: 700;
  margin-bottom: 0.45rem;
  color: #7f1d1d;
}

.ss-mermaid-error-detail {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  overflow-wrap: anywhere;
  font-size: 0.76rem;
  line-height: 1.4;
  background: transparent;
  border: 0;
  padding: 0;
  color: #991b1b;
  font-weight: 500;
  max-width: 100%;
}

.summary-search-highlight {
  background: #fde68a;
  color: inherit;
  border-radius: 4px;
  padding: 0 0.1em;
}

.ss-streaming-content {
  line-height: 1.7;
}
</style>
