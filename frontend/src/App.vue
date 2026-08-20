<script setup lang="ts">
import { computed, watch, ref } from 'vue'
import { PhMonitorPlay, PhList } from '@phosphor-icons/vue'
import { marked } from 'marked'
import { useTaskViewModel } from './composables/useTaskViewModel'
import { useFolderViewModel } from './composables/useFolderViewModel'
import { useMermaidViewer } from './composables/useMermaidViewer'
import {
  useSummaryImageExporter,
  createDefaultSummaryImageExportSettings,
  type SummaryImagePreviewPage,
  type SummaryImageExportSettings,
  type SummaryImageLayoutPreset,
  type SummaryImageFormat,
  type SummaryImageMetaMode,
  type SummaryImageRenderProgress,
} from './composables/useSummaryImageExporter'
import { useToast } from './composables/useToast'
import { stripDoubleBracePlaceholders } from './utils/formatters'
import { postProcessCompiledMarkdown } from './utils/markdownPostProcessor'
import type { Task, MarkdownHeadingItem, BilibiliVideoInfo, BilibiliPartsConfig, LocalFolderScanResult } from './types'
import Sidebar from './components/Sidebar.vue'
import FloatingToolbar from './components/FloatingToolbar.vue'
import TaskInfoModal from './components/TaskInfoModal.vue'
import TaskContentArea from './components/TaskContentArea.vue'
import MermaidViewerModal from './components/MermaidViewerModal.vue'
import SummaryImageWorkbenchModal from './components/SummaryImageWorkbenchModal.vue'
import SettingsModal from './components/SettingsModal.vue'
import BilibiliPartsSelector from './components/BilibiliPartsSelector.vue'
import LocalFolderSelector from './components/LocalFolderSelector.vue'
import ToastContainer from './components/ToastContainer.vue'

const {
  tasks,
  selectedTask,
  videoUrl,
  selectedFile,
  localFilePath,
  isLocalClient,
  quality,
  summaryMode,
  isSubmitting,
  error,
  activeTab,
  llmProviders,
  llmSettings,
  isUpdatingLlmSettings,
  activeProfileId,
  editingProfileId,
  profileFormState,
  isSwitchingProfile,
  transcriptionSettings,
  isUpdatingTranscriptionSettings,
  summarizationSettings,
  isUpdatingSummarizationSettings,
  isReadingBilibiliCookieFromBrowser,
  isMultiSelectMode,
  selectedTaskIds,
  streamingBuffer,
  streamingTaskId,
  isPrewarming,
  resumeSnapshot,
  takeResumeSnapshot,
  clearResumeSnapshot,
  resetStreamingState,
  submitTask,
  cancelSubmitting,
  selectTask,
  downloadContent,
  copyContent,
  isSidebarOpen,
  deleteTask,
  reSummarize,
  reTranscribe,
  updateTaskTopic,
  updateProfile,
  createProfile,
  deleteProfile,
  switchActiveProfile,
  editProfile,
  updateTranscriptionSettings,
  updateSummarizationSettings,
  testLlm,
  readBilibiliCookieFromBrowser,
  checkBilibiliVideoInfo,
  submitTaskWithParts,
  isBilibiliUrl,
  checkLocalPath,
  scanLocalFolder,
  submitLocalPathTasks,
  toggleMultiSelectMode,
  toggleTaskSelection,
  selectAllTasks,
  clearSelection,
  batchReSummarize,
  batchReTranscribe,
  batchDownloadMarkdown,
  batchDelete,
  toggleFolderSelection,
} = useTaskViewModel()

const {
  folders,
  folderTree,
  createFolder,
  renameFolder,
  deleteFolder,
  moveFolder,
  assignTaskToFolder,
} = useFolderViewModel()

// 状态变量
const showInfoModal = ref(false)
const isSettingsModalOpen = ref(false)
const isEditingTopic = ref(false)
const editingTopicValue = ref('')
const isTestingLlm = ref(false)
const summaryHighlightRequest = ref<{
  taskId: string
  keyword: string
  source: 'topic' | 'summary'
  requestId: number
} | null>(null)
const markdownHeadings = ref<MarkdownHeadingItem[]>([])
const activeHeadingId = ref('')
const headingJumpRequest = ref<{ id: string; requestId: number } | null>(null)
const headingJumpSeq = ref(0)

// B站分P选择器状态
const isBilibiliPartsSelectorOpen = ref(false)
const bilibiliVideoInfo = ref<BilibiliVideoInfo | null>(null)
const isCheckingBilibiliVideoInfo = ref(false)
const pendingBilibiliUrl = ref('')

// 本地文件夹选择器状态
const isLocalFolderSelectorOpen = ref(false)
const localFolderInfo = ref<LocalFolderScanResult | null>(null)
const isScanningLocalFolder = ref(false)

// Mermaid 查看器
const mermaidViewerModalRef = ref<{
  stage: HTMLElement | null
  viewport: HTMLElement | null
} | null>(null)

// Toast 通知
const { toasts, removeToast, success, info, error: toastError } = useToast()

const {
  showMermaidViewer,
  currentMermaidSvg,
  currentZoom,
  openMermaidViewer,
  closeMermaidViewer,
  resetView,
  fitView,
  zoomIn,
  zoomOut,
} = useMermaidViewer(mermaidViewerModalRef)

const { exportSummaryAsImage, generateSummaryImagePreview } = useSummaryImageExporter()

const SUMMARY_IMAGE_SETTINGS_STORAGE_KEY = 'ShengWen:summary-image-export-settings'

const summaryLayoutOptions: Array<{ label: string; value: SummaryImageLayoutPreset }> = [
  { label: '9:16 手机竖版', value: 'mobile-9-16' },
  { label: '9:32 长屏', value: 'mobile-9-32' },
  { label: '9:64 超长图', value: 'mobile-9-64' },
  { label: '长图原始比例', value: 'long' },
]

const summaryMetaModeOptions: Array<{ label: string; value: SummaryImageMetaMode }> = [
  { label: '每个图片顶端都显示元信息', value: 'all-pages' },
  { label: '仅第一张图顶部显示元信息', value: 'first-page-only' },
]

const summaryFormatOptions: Array<{ label: string; value: SummaryImageFormat }> = [
  { label: 'JPEG（推荐）', value: 'jpeg' },
  { label: 'WebP（更小）', value: 'webp' },
  { label: 'PNG（无损）', value: 'png' },
]

const summaryWidthOptions = [960, 1080, 1242, 1440]
const summaryPixelRatioOptions = [1, 1.25, 1.5, 1.8, 2]

const loadSummaryImageSettings = (): SummaryImageExportSettings => {
  const defaults = createDefaultSummaryImageExportSettings()
  try {
    const raw = localStorage.getItem(SUMMARY_IMAGE_SETTINGS_STORAGE_KEY)
    if (!raw) return defaults
    const parsed = JSON.parse(raw) as Partial<SummaryImageExportSettings>
    const merged: SummaryImageExportSettings = {
      ...defaults,
      ...parsed,
    }
    if (!summaryLayoutOptions.some((option) => option.value === merged.layoutPreset)) {
      merged.layoutPreset = defaults.layoutPreset
    }
    if (!summaryMetaModeOptions.some((option) => option.value === merged.metaMode)) {
      merged.metaMode = defaults.metaMode
    }
    return merged
  } catch {
    return defaults
  }
}

const summaryImageSettings = ref<SummaryImageExportSettings>(loadSummaryImageSettings())
const isSummaryImageSettingsOpen = ref(false)
const isSummaryPreviewRendering = ref(false)
const summaryRenderProgress = ref<{ current: number; total: number } | null>(null)
const summaryPreviewDirty = ref(true)
const summaryPreviewPages = ref<SummaryImagePreviewPage[]>([])
const summaryPreviewActiveIndex = ref(0)
const summaryPreviewTotalSizeKB = ref(0)
const showAllPreviewPages = ref(false)

const getSummaryImageExportPayload = () => {
  if (!selectedTask.value?.summary) return null
  return {
    task: selectedTask.value,
    topic: topic.value || selectedTask.value.title || 'AI 总结',
    compiledMarkdown: compiledMarkdown.value,
    rawSummary: selectedTask.value.summary,
  }
}

const canRefreshSummaryPreview = computed(() => {
  if (!isSummaryImageSettingsOpen.value) return false
  if (!summaryPreviewDirty.value) return false
  if (isSummaryPreviewRendering.value) return false
  return !!getSummaryImageExportPayload()
})

const summaryRefreshButtonLabel = computed(() => {
  if (isSummaryPreviewRendering.value) return '重新生成中...'
  if (summaryPreviewDirty.value) return '参数已变更，点击刷新'
  return '预览已是最新'
})

let summaryPreviewSequence = 0

const refreshSummaryImagePreview = async (options?: { manual?: boolean; force?: boolean }) => {
  if (!isSummaryImageSettingsOpen.value) return

  const payload = getSummaryImageExportPayload()
  if (!payload) return

  if (!options?.force && !summaryPreviewDirty.value) return

  if (options?.manual) {
    info('正在重新生成预览图...')
  }

  const currentSequence = ++summaryPreviewSequence
  isSummaryPreviewRendering.value = true
  summaryRenderProgress.value = null
  summaryPreviewPages.value = []

  try {
    const preview = await generateSummaryImagePreview(
      payload,
      summaryImageSettings.value,
      (progress: SummaryImageRenderProgress) => {
        summaryRenderProgress.value = { current: progress.current, total: progress.total }
        if (progress.page) {
          summaryPreviewPages.value = [...summaryPreviewPages.value, progress.page]
        }
      },
    )
    if (currentSequence !== summaryPreviewSequence) return

    summaryPreviewTotalSizeKB.value = preview.totalSizeKB
    summaryPreviewActiveIndex.value = Math.min(
      summaryPreviewActiveIndex.value,
      Math.max(0, preview.pages.length - 1),
    )
    summaryPreviewDirty.value = false

    if (options?.manual) {
      success(`预览已更新：共 ${preview.pages.length} 张，约 ${preview.totalSizeKB}KB`)
    }
  } catch (_error) {
    if (currentSequence === summaryPreviewSequence) {
      toastError('预览生成失败，请调整参数后重试')
    }
  } finally {
    if (currentSequence === summaryPreviewSequence) {
      isSummaryPreviewRendering.value = false
      summaryRenderProgress.value = null
    }
  }
}

const handleOpenSummaryImageSettings = () => {
  if (!selectedTask.value?.summary) {
    toastError('暂无可导出的 AI 总结')
    return
  }

  isSummaryImageSettingsOpen.value = true
  showAllPreviewPages.value = false
  summaryPreviewActiveIndex.value = 0
  summaryPreviewDirty.value = true
  void refreshSummaryImagePreview({ force: true })
}

const handleRefreshSummaryImagePreview = () => {
  void refreshSummaryImagePreview({ manual: true })
}

const handleSelectPreviewPage = (index: number) => {
  if (index < 0 || index >= summaryPreviewPages.value.length) return
  summaryPreviewActiveIndex.value = index
}

const handlePreviewPagePrev = () => {
  if (summaryPreviewActiveIndex.value <= 0) return
  summaryPreviewActiveIndex.value -= 1
}

const handlePreviewPageNext = () => {
  if (summaryPreviewActiveIndex.value >= summaryPreviewPages.value.length - 1) return
  summaryPreviewActiveIndex.value += 1
}

const handleCloseSummaryImageSettings = () => {
  isSummaryImageSettingsOpen.value = false
}

const handleCloseViewer = () => {
  closeMermaidViewer()
}

// 包装删除任务，添加成功反馈
const handleDeleteTask = async (taskId: string) => {
  const result = await deleteTask(taskId)
  if (result) {
    success('任务已删除')
  }
}

const handleCopySummary = async () => {
  const result = await copyContent('summary')
  if (result) {
    success('AI 总结已复制到剪贴板')
  } else {
    toastError('复制失败，内容为空')
  }
}

const handleCopyTranscript = async () => {
  const result = await copyContent('transcript')
  if (result) {
    success('转录文本已复制到剪贴板')
  } else {
    toastError('复制失败，内容为空')
  }
}

const handleReSummarize = (taskId: string) => {
  const { info } = useToast()
  info('正在重新生成 AI 总结...')
  reSummarize(taskId)
}

const handleReTranscribe = (taskId: string) => {
  const { info } = useToast()
  info('正在重新转录原文...')
  reTranscribe(taskId)
}

const handleDownloadMarkdown = () => {
  success('开始下载 AI 总结...')
  downloadContent('summary')
}

const handleDownloadTxt = () => {
  success('开始下载转录文本...')
  downloadContent('transcript')
}

const handleTestLlm = async () => {
  isTestingLlm.value = true
  const { info, success, error, warning } = useToast()
  info('正在测试 LLM 连接...')

  try {
    const result = await testLlm()

    if (result.status === 'success') {
      success(result.message)
    } else if (result.status === 'warning') {
      warning(result.message)
    } else {
      error(result.message)
    }
  } catch (err) {
    error(`测试失败: ${err instanceof Error ? err.message : '未知错误'}`)
  } finally {
    isTestingLlm.value = false
  }
}

const handleExportSummaryImage = async () => {
  const payload = getSummaryImageExportPayload()
  if (!payload) {
    toastError('暂无可导出的 AI 总结')
    return
  }

  const { info } = useToast()
  info('正在生成分享图片...')

  try {
    const result = await exportSummaryAsImage(payload, summaryImageSettings.value)
    if (result.files > 1) {
      success(`导出成功：共 ${result.files} 张，约 ${result.totalSizeKB}KB`)
    } else {
      const first = result.pages[0]
      if (first) {
        success(`导出成功：${first.width}x${first.height} · ${first.sizeKB}KB`)
      } else {
        success('导出成功')
      }
    }
  } catch (_error) {
    toastError('成图失败，请稍后重试')
  }
}

const handleUpdateLlmSettings = async (payload: {
  profile_id: string
  name?: string
  provider?: string
  base_url?: string
  api_key?: string
  model_id?: string
  temperature?: number
}) => {
  try {
    await updateProfile(payload)
    success('LLM 配置已更新')
  } catch (_e) {}
}

const handleUpdateLlmSettingsAndTest = async (payload: {
  profile_id: string
  name?: string
  provider?: string
  base_url?: string
  api_key?: string
  model_id?: string
  temperature?: number
}) => {
  try {
    await updateProfile(payload)
    success('LLM 配置已更新')
    await handleTestLlm()
  } catch (_e) {}
}

const handleCreateProfile = async (name: string, provider: string) => {
  try {
    await createProfile(name, provider)
    success('配置已创建')
  } catch (_e) {}
}

const handleDeleteProfile = async (profileId: string) => {
  try {
    await deleteProfile(profileId)
    success('配置已删除')
  } catch (_e) {}
}

const handleSwitchActiveProfile = async (profileId: string) => {
  try {
    await switchActiveProfile(profileId)
  } catch (_e) {}
}

const handleEditProfile = (profileId: string) => {
  editProfile(profileId)
}

const handleUpdateTranscriptionSettings = async (payload: {
  device?: 'cpu' | 'cuda'
  model_source?: 'auto_download' | 'manual_path'
  model_size?: 'tiny' | 'base' | 'small' | 'medium' | 'large'
  model_path?: string
  compute_type_mode?: 'auto' | 'manual'
  compute_type?: 'int8' | 'float16' | 'float32' | 'bfloat16'
  enable_bilibili_subtitle_fetch?: boolean
  bilibili_sessdata?: string
  clear_bilibili_sessdata?: boolean
}) => {
  try {
    await updateTranscriptionSettings(payload)
    success('转录配置已更新')
  } catch (_e) {
    // 错误信息由 useTaskViewModel + Toast 统一处理
  }
}

const handleReadBilibiliCookieFromBrowser = async () => {
  try {
    const result = await readBilibiliCookieFromBrowser()
    if (result.success) {
      success(`已从 ${result.source_browser} 读取 Cookie`)
    } else {
      toastError(result.error || '读取失败')
    }
  } catch (_e) {
    // 错误信息由 useTaskViewModel + Toast 统一处理
  }
}

// B站分P处理
const handleSubmit = async () => {
  // localhost 场景优先使用本地路径直读（避免文件上传复制）
  if (isLocalClient && localFilePath.value.trim()) {
    // 先检查路径类型
    const pathCheck = await checkLocalPath(localFilePath.value.trim())

    // 处理检查失败的情况
    if (!pathCheck) {
      toastError('无法检查本地路径，请确认服务器是否正常运行')
      return
    }

    if (pathCheck.type === 'not_found') {
      toastError(`路径不存在: ${pathCheck.path}`)
      return
    }

    if (pathCheck.type === 'folder') {
      // 是文件夹，扫描并弹出选择器
      isScanningLocalFolder.value = true
      try {
        const scanResult = await scanLocalFolder(localFilePath.value.trim())
        if (scanResult && scanResult.files.length > 0) {
          localFolderInfo.value = scanResult
          isLocalFolderSelectorOpen.value = true
        } else if (scanResult && scanResult.files.length === 0) {
          toastError('文件夹中没有找到支持的视频/音频文件')
        } else {
          toastError('扫描文件夹失败，请重试')
        }
      } catch (err) {
        const errMsg = err instanceof Error ? err.message : '扫描文件夹失败'
        toastError(errMsg)
      } finally {
        isScanningLocalFolder.value = false
      }
      return
    }

    // 是文件，直接提交
    await submitTask()
    return
  }

  // 文件上传
  if (selectedFile.value) {
    await submitTask()
    return
  }

  // URL 提交 - 检查是否为B站多P视频
  const url = videoUrl.value.trim()
  if (!url) {
    error.value = '请输入有效视频链接，或粘贴包含链接的文本。'
    return
  }

  if (isBilibiliUrl(url)) {
    // 检查是否为多P视频
    isCheckingBilibiliVideoInfo.value = true
    pendingBilibiliUrl.value = url
    try {
      const info = await checkBilibiliVideoInfo(url)
      if (info && info.is_multi_part) {
        // 是多P视频，显示选择器
        bilibiliVideoInfo.value = info
        isBilibiliPartsSelectorOpen.value = true
        isSubmitting.value = false
      } else {
        // 单P视频，直接提交
        await submitTask()
      }
    } catch (err) {
      // 检查失败，直接提交（后端会处理）
      console.error('Failed to check Bilibili video info:', err)
      await submitTask()
    } finally {
      isCheckingBilibiliVideoInfo.value = false
    }
  } else {
    // 非B站视频，直接提交
    await submitTask()
  }
}

const handleBilibiliPartsConfirm = async (config: BilibiliPartsConfig) => {
  isBilibiliPartsSelectorOpen.value = false
  try {
    await submitTaskWithParts(pendingBilibiliUrl.value, config)
    videoUrl.value = ''
    success('已提交任务')
  } catch (_e) {
    // 错误信息由 useTaskViewModel + Toast 统一处理
  }
}

const handleBilibiliPartsClose = () => {
  isBilibiliPartsSelectorOpen.value = false
  bilibiliVideoInfo.value = null
  pendingBilibiliUrl.value = ''
}

const handleLocalFolderConfirm = async (config: { mode: 'merge' | 'separate'; paths: string[] }) => {
  isLocalFolderSelectorOpen.value = false
  try {
    await submitLocalPathTasks(config.paths, config.mode)
    localFilePath.value = ''
    if (config.paths.length > 1) {
      success(`已提交 ${config.paths.length} 个任务`)
    } else {
      success('已提交任务')
    }
  } catch (_e) {
    // 错误信息由 useTaskViewModel + Toast 统一处理
  }
}

const handleLocalFolderClose = () => {
  isLocalFolderSelectorOpen.value = false
  localFolderInfo.value = null
}

const startEditingTopic = () => {
  editingTopicValue.value = topic.value || selectedTask.value?.title || ''
  isEditingTopic.value = true
}

const saveTopic = async () => {
  if (!selectedTask.value) return
  try {
    await updateTaskTopic(selectedTask.value.id, editingTopicValue.value)
    isEditingTopic.value = false
    success('主题已更新')
  } catch (e) {
    // Error handled in composable and shown via toast
  }
}

const cancelEditingTopic = () => {
  isEditingTopic.value = false
}

const handleSelectTask = async (task: Task) => {
  summaryHighlightRequest.value = null
  markdownHeadings.value = []
  activeHeadingId.value = ''
  headingJumpRequest.value = null
  await selectTask(task)
  // 如果选中了正在流式输出的任务，拍快照用于无缝显示已有内容
  if (selectedTask.value?.status === 'SUMMARIZING' && selectedTask.value.summary) {
    takeResumeSnapshot(selectedTask.value.summary)
  } else {
    clearResumeSnapshot()
  }
}

const handleFocusSearchMatch = (payload: {
  taskId: string
  keyword: string
  source: 'topic' | 'summary'
  requestId: number
}) => {
  activeTab.value = 'summary'
  summaryHighlightRequest.value = payload
}

const handleJumpHeading = (headingId: string) => {
  headingJumpSeq.value += 1
  headingJumpRequest.value = {
    id: headingId,
    requestId: headingJumpSeq.value,
  }
}

const handleUpdateSummarizationSettings = async (payload: {
  chunk_target_duration_sec?: number
  chunk_min_duration_sec?: number
  chunk_max_duration_sec?: number
  boundary_jump_sec?: number
  auto_chunk_min_audio_duration_sec?: number
  auto_chunk_min_transcript_lines?: number
  max_agent_value_chars?: number
  fallback_to_standard_on_agent_error?: boolean
}) => {
  try {
    await updateSummarizationSettings(payload)
    success('总结配置已更新')
  } catch (_e) {
    // 错误信息由 useTaskViewModel + Toast 统一处理
  }
}

const handleMarkdownHeadingsUpdate = (headings: MarkdownHeadingItem[]) => {
  markdownHeadings.value = headings
}

const handleActiveHeadingIdUpdate = (headingId: string) => {
  activeHeadingId.value = headingId
}

// 错误处理
watch(error, (newError) => {
  if (newError) {
    toastError(newError)
  }
})

watch(summaryImageSettings, (nextSettings) => {
  try {
    localStorage.setItem(SUMMARY_IMAGE_SETTINGS_STORAGE_KEY, JSON.stringify(nextSettings))
  } catch {
    // Ignore persistence failure.
  }
  if (isSummaryImageSettingsOpen.value) {
    summaryPreviewDirty.value = true
  }
}, { deep: true })

// 配置 marked 渲染器以支持 mermaid 类名
const renderer = new marked.Renderer()
renderer.code = ({ text, lang }) => {
  if (lang === 'mermaid') {
    return `<pre class="mermaid">${text}</pre>`
  }
  return `<pre><code class="language-${lang}">${text}</code></pre>`
}
marked.setOptions({ renderer })

const compiledMarkdown = computed(() => {
  if (!selectedTask.value?.summary) return ''
  const cleanedSummary = stripDoubleBracePlaceholders(selectedTask.value.summary)
  const html = marked.parse(cleanedSummary) as string
  return postProcessCompiledMarkdown(html, {
    videoUrl: selectedTask.value.video_url || '',
  })
})

// 切回来时用的已有内容快照（编译为 HTML 后不再响应 task.summary 更新，避免闪烁）
const compiledResumeSummary = computed(() => {
  if (!resumeSnapshot.value) return ''
  const cleaned = stripDoubleBracePlaceholders(resumeSnapshot.value)
  const html = marked.parse(cleaned) as string
  return postProcessCompiledMarkdown(html, {
    videoUrl: selectedTask.value?.video_url || '',
  })
})

const isStreamingSummary = computed(() =>
  streamingTaskId.value === selectedTask.value?.id
  && selectedTask.value?.status === 'SUMMARIZING'
)

// 预热完成时弹出提示
watch(isPrewarming, (val) => {
  if (!val) {
    const { success } = useToast()
    success('系统预热完成，已准备就绪')
  }
})

const streamingBlocks = computed(() =>
  isStreamingSummary.value ? streamingBuffer.value : []
)

watch(() => selectedTask.value?.status, (newStatus) => {
  if (newStatus === 'COMPLETED' || newStatus === 'FAILED') {
    resetStreamingState()
    clearResumeSnapshot()
  }
})

const topic = computed(() => {
  if (selectedTask.value?.topic) return selectedTask.value.topic
  if (!selectedTask.value?.summary) return ''
  const match = selectedTask.value.summary.match(/\{\{(.*?)\}\}/i)
  if (match && match[1]) {
    return match[1].trim()
  }
  return ''
})

watch(
  [
    () => isSummaryImageSettingsOpen.value,
    () => selectedTask.value?.id,
    compiledMarkdown,
    topic,
  ],
  () => {
    if (isSummaryImageSettingsOpen.value) {
      summaryPreviewDirty.value = true
    }
  },
)
</script>

<template>
  <div class="flex h-[100dvh] w-full overflow-hidden bg-bg text-slate-800 font-sans relative">
    <!-- Toast 通知容器 -->
    <ToastContainer
      :toasts="toasts"
      position="bottom-right"
      class="md:block hidden"
      @close="removeToast"
    />
    <ToastContainer
      :toasts="toasts"
      position="bottom-center"
      class="block md:hidden"
      @close="removeToast"
    />

    <!-- 设置弹窗 -->
    <SettingsModal
      :isOpen="isSettingsModalOpen"
      :llmProviders="llmProviders"
      :llmSettings="llmSettings"
      :activeProfileId="activeProfileId"
      :editingProfileId="editingProfileId"
      :profileFormState="profileFormState"
      :isUpdatingLlmSettings="isUpdatingLlmSettings"
      :isTestingLlm="isTestingLlm"
      :isSwitchingProfile="isSwitchingProfile"
      :isPrewarming="isPrewarming"
      :transcriptionSettings="transcriptionSettings"
      :isUpdatingTranscriptionSettings="isUpdatingTranscriptionSettings"
      :summarizationSettings="summarizationSettings"
      :isUpdatingSummarizationSettings="isUpdatingSummarizationSettings"
      :isReadingBilibiliCookieFromBrowser="isReadingBilibiliCookieFromBrowser"
      @close="isSettingsModalOpen = false"
      @switchActiveProfile="handleSwitchActiveProfile"
      @editProfile="handleEditProfile"
      @createProfile="handleCreateProfile"
      @deleteProfile="handleDeleteProfile"
      @updateLlmSettings="handleUpdateLlmSettings"
      @updateLlmSettingsAndTest="handleUpdateLlmSettingsAndTest"
      @testLlm="handleTestLlm"
      @updateTranscriptionSettings="handleUpdateTranscriptionSettings"
      @readBilibiliCookieFromBrowser="handleReadBilibiliCookieFromBrowser"
      @updateSummarizationSettings="handleUpdateSummarizationSettings"
    />

    <!-- 遮罩层 (Mobile Only) -->
    <transition name="fade">
      <div v-if="isSidebarOpen" @click="isSidebarOpen = false" class="fixed inset-0 bg-slate-900/50 z-30 backdrop-blur-sm md:hidden"></div>
    </transition>

    <!-- 左侧边栏 -->
    <Sidebar
      v-model:videoUrl="videoUrl"
      v-model:selectedFile="selectedFile"
      v-model:localFilePath="localFilePath"
      v-model:quality="quality"
      v-model:summaryMode="summaryMode"
      v-model:isSidebarOpen="isSidebarOpen"
      :isLocalClient="isLocalClient"
      :tasks="tasks"
      :selectedTask="selectedTask"
      :isSubmitting="isSubmitting"
      :isPrewarming="isPrewarming"
      :llmProviders="llmProviders"
      :llmSettings="llmSettings"
      :activeProfileId="activeProfileId"
      :editingProfileId="editingProfileId"
      :profileFormState="profileFormState"
      :isUpdatingLlmSettings="isUpdatingLlmSettings"
      :isTestingLlm="isTestingLlm"
      :isSwitchingProfile="isSwitchingProfile"
      :transcriptionSettings="transcriptionSettings"
      :isUpdatingTranscriptionSettings="isUpdatingTranscriptionSettings"
      :summarizationSettings="summarizationSettings"
      :isUpdatingSummarizationSettings="isUpdatingSummarizationSettings"
      :folders="folders"
      :folderTree="folderTree"
      :isMultiSelectMode="isMultiSelectMode"
      :selectedTaskIds="selectedTaskIds"
      @submit="handleSubmit"
      @cancelSubmit="cancelSubmitting"
      @selectTask="handleSelectTask"
      @deleteTask="handleDeleteTask"
      @updateLlmSettings="handleUpdateLlmSettings"
      @switchActiveProfile="handleSwitchActiveProfile"
      @editProfile="handleEditProfile"
      @createProfile="handleCreateProfile"
      @deleteProfile="handleDeleteProfile"
      @updateTranscriptionSettings="handleUpdateTranscriptionSettings"
      @updateSummarizationSettings="handleUpdateSummarizationSettings"
      @startTestLlm="handleTestLlm"
      @focusSearchMatch="handleFocusSearchMatch"
      @showInfo="(task) => { handleSelectTask(task); showInfoModal = true; }"
      @openSettings="isSettingsModalOpen = true"
      @createFolder="(name: string, parentId: string | null) => createFolder(name, parentId)"
      @renameFolder="(folderId: string, newName: string) => renameFolder(folderId, newName)"
      @deleteFolder="deleteFolder"
      @assignTaskToFolder="(taskId: string, folderId: string | null) => assignTaskToFolder(taskId, folderId)"
      @moveFolder="(folderId: string, newParentId: string | null) => moveFolder(folderId, newParentId)"
      @toggleMultiSelectMode="toggleMultiSelectMode"
      @toggleTaskSelection="toggleTaskSelection"
      @selectAllTasks="selectAllTasks"
      @clearSelection="clearSelection"
      @batchReSummarize="batchReSummarize"
      @batchReTranscribe="batchReTranscribe"
      @batchDownloadMarkdown="batchDownloadMarkdown"
      @batchDelete="batchDelete"
      @toggleFolderSelection="toggleFolderSelection"
    />

    <!-- 右侧内容区 -->
    <main class="flex-1 flex flex-col h-full bg-gray-50 relative w-full overflow-hidden">
      <template v-if="selectedTask">
        <!-- 悬浮气泡工具栏 -->
        <FloatingToolbar
          v-model:activeTab="activeTab"
          :selectedTask="selectedTask"
          :isSidebarOpen="isSidebarOpen"
          :headings="markdownHeadings"
          :active-heading-id="activeHeadingId"
          @reSummarize="handleReSummarize(selectedTask.id)"
          @reTranscribe="handleReTranscribe(selectedTask.id)"
          @copySummary="handleCopySummary"
          @copyTranscript="handleCopyTranscript"
          @downloadMarkdown="handleDownloadMarkdown"
          @downloadTxt="handleDownloadTxt"
          @exportSummaryImage="handleExportSummaryImage"
          @openSummaryImageSettings="handleOpenSummaryImageSettings"
          @toggleSidebar="isSidebarOpen = true"
          @jumpHeading="handleJumpHeading"
        />

        <!-- 内容滚动区 -->
        <TaskContentArea
          :task="selectedTask"
          :active-tab="activeTab"
          :compiled-markdown="compiledMarkdown"
          :summary-highlight-request="summaryHighlightRequest"
          :heading-jump-request="headingJumpRequest"
          :topic="topic"
          :is-editing-topic="isEditingTopic"
          :editing-topic-value="editingTopicValue"
          :is-streaming-summary="isStreamingSummary"
          :streaming-blocks="streamingBlocks"
          :compiled-resume-summary="compiledResumeSummary"
          @open-mermaid-viewer="openMermaidViewer"
          @start-edit-topic="startEditingTopic"
          @save-topic="saveTopic"
          @cancel-edit-topic="cancelEditingTopic"
          @update:editing-topic-value="(val) => editingTopicValue = val"
          @update-markdown-headings="handleMarkdownHeadingsUpdate"
          @update-active-heading-id="handleActiveHeadingIdUpdate"
        />
      </template>

      <!-- 未选中状态 -->
      <div v-else class="flex-1 flex flex-col h-full">
        <!-- 移动端顶部栏（未选中任务时显示） -->
        <header class="h-14 bg-white border-b border-gray-100 px-4 flex items-center md:hidden shrink-0 sticky top-0 z-20">
          <button @click="isSidebarOpen = true" class="p-1.5 -ml-1.5 text-slate-600 hover:bg-gray-100 rounded-lg active:scale-90 transition-transform">
            <PhList :size="24" />
          </button>
        </header>

        <div class="flex-1 flex flex-col items-center justify-center text-slate-400">
          <PhMonitorPlay :size="64" weight="thin" class="mb-4 opacity-20" />
          <p>请从左侧选择一个任务查看详情</p>
        </div>
      </div>
    </main>

    <!-- 任务信息模态框 -->
    <TaskInfoModal
      v-model:show="showInfoModal"
      :selectedTask="selectedTask"
    />
    
    <!-- Mermaid 查看器模态框 -->
    <MermaidViewerModal
      ref="mermaidViewerModalRef"
      :show="showMermaidViewer"
      :current-zoom="currentZoom"
      :svg-content="currentMermaidSvg"
      @close="handleCloseViewer"
      @fit-view="fitView"
      @zoom-in="zoomIn"
      @zoom-out="zoomOut"
      @reset-view="resetView"
    />

    <SummaryImageWorkbenchModal
      :show="isSummaryImageSettingsOpen"
      v-model:settings="summaryImageSettings"
      v-model:showAllPreviewPages="showAllPreviewPages"
      :layout-options="summaryLayoutOptions"
      :meta-mode-options="summaryMetaModeOptions"
      :format-options="summaryFormatOptions"
      :width-options="summaryWidthOptions"
      :pixel-ratio-options="summaryPixelRatioOptions"
      :is-preview-rendering="isSummaryPreviewRendering"
      :render-progress="summaryRenderProgress"
      :preview-dirty="summaryPreviewDirty"
      :can-refresh-preview="canRefreshSummaryPreview"
      :refresh-button-label="summaryRefreshButtonLabel"
      :preview-pages="summaryPreviewPages"
      :preview-active-index="summaryPreviewActiveIndex"
      :preview-total-size-kb="summaryPreviewTotalSizeKB"
      @close="handleCloseSummaryImageSettings"
      @refresh-preview="handleRefreshSummaryImagePreview"
      @export-image="handleExportSummaryImage"
      @preview-prev="handlePreviewPagePrev"
      @preview-next="handlePreviewPageNext"
      @select-preview-page="handleSelectPreviewPage"
    />

    <!-- B站分P选择器 -->
    <BilibiliPartsSelector
      :isOpen="isBilibiliPartsSelectorOpen"
      :videoInfo="bilibiliVideoInfo"
      :isLoading="isCheckingBilibiliVideoInfo"
      @close="handleBilibiliPartsClose"
      @confirm="handleBilibiliPartsConfirm"
    />

    <!-- 本地文件夹选择器 -->
    <LocalFolderSelector
      :isOpen="isLocalFolderSelectorOpen"
      :folderInfo="localFolderInfo"
      :isLoading="isScanningLocalFolder"
      @close="handleLocalFolderClose"
      @confirm="handleLocalFolderConfirm"
    />
  </div>
</template>

<style>
/* 移动端过渡动画 */
.fade-enter-active, .fade-leave-active { transition: opacity 0.3s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

/* 移动端点击高亮优化 */
html, body { -webkit-tap-highlight-color: transparent; }
</style>

