import type { Task } from '../types'
import html2canvas from 'html2canvas'
import { normalizeMermaidSvgLayout } from '../utils/mermaidLayout'
import {
  formatDuration,
  formatTranscriptionDuration,
  formatConversionRatio,
  formatDateTime,
  countWords,
  stripDoubleBracePlaceholders,
} from '../utils/formatters'
import { getCurrentTheme, type MarkdownTheme } from './useMarkdownTheme'
import { normalizeAccidentalInlineCodeBlocks } from '../utils/markdownNormalizer'
import { getMermaid } from '../utils/mermaidLoader'

export type SummaryImageLayoutPreset = 'long' | 'mobile-9-16' | 'mobile-9-32' | 'mobile-9-64'
export type SummaryImageFormat = 'png' | 'jpeg' | 'webp'
export type SummaryImageMetaMode = 'all-pages' | 'first-page-only'

export interface SummaryImageExportPayload {
  task: Task
  topic: string
  compiledMarkdown: string
  rawSummary: string
  shareUrl?: string
}

export interface SummaryImageExportSettings {
  width: number
  pixelRatio: number
  layoutPreset: SummaryImageLayoutPreset
  metaMode: SummaryImageMetaMode
  format: SummaryImageFormat
  quality: number
  targetSizeKB: number
  fontScale: number
  contentPaddingScale: number
}

export interface SummaryImagePreviewPage {
  index: number
  dataUrl: string
  width: number
  height: number
  sizeKB: number
  format: SummaryImageFormat
}

export interface SummaryImagePreviewResult {
  pages: SummaryImagePreviewPage[]
  totalSizeKB: number
  format: SummaryImageFormat
}

export interface SummaryImageRenderProgress {
  current: number
  total: number
  page: SummaryImagePreviewPage | null
}

export type SummaryImageProgressCallback = (progress: SummaryImageRenderProgress) => void

export interface SummaryImageExportPageResult {
  index: number
  filename: string
  width: number
  height: number
  sizeKB: number
}

export interface SummaryImageExportResult {
  files: number
  mode: 'single' | 'multi'
  totalSizeKB: number
  format: SummaryImageFormat
  filenames: string[]
  pages: SummaryImageExportPageResult[]
}

interface RenderPageContext {
  card: HTMLElement
  summaryContent: HTMLElement
}

const BASE_EXPORT_WIDTH = 1080
const DEFAULT_SHARE_URL = 'https://github.com/zzyong24/ShengWen'
const EXPORT_FONT_FAMILY = "'Microsoft YaHei', 'Segoe UI', 'Consolas', sans-serif"
const HEADER_HORIZONTAL_PADDING = 44
const CONTENT_HORIZONTAL_PADDING = 76
const CONTENT_TOP_PADDING = 34
const CONTENT_BOTTOM_PADDING = 28
const SUMMARY_FONT_SIZE = 35
const SUMMARY_LINE_HEIGHT = 1.62
const MERMAID_FONT_RATIO = 0.25
const BASE_REFERENCE_FONT_SIZE = 18
const BASE_FONT_SCALE = SUMMARY_FONT_SIZE / BASE_REFERENCE_FONT_SIZE
const JPEG_WEBP_MIN_QUALITY = 0.45
const JPEG_WEBP_MAX_QUALITY = 0.98
const OVERSIZE_MIN_SCALE = 0.35
const DOWNLOAD_GAP_MS = 80
const PREVIEW_PIXEL_RATIO_CAP = 1.5
const REUSE_PIXEL_RATIO_EPSILON = 0.02
const EXPORT_QUOTE_CHARS_RE = /[“”‘’]/g

interface RenderCanvasCacheEntry {
  signature: string
  effectivePixelRatio: number
  canvases: HTMLCanvasElement[]
}

const hashText = (input: string) => {
  let hash = 2166136261
  for (let i = 0; i < input.length; i += 1) {
    hash ^= input.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(36)
}

const formatNumberKey = (value: number) => {
  return String(Math.round(value * 1000) / 1000)
}

const createRenderSignature = (
  payload: SummaryImageExportPayload,
  settings: SummaryImageExportSettings,
  themeId: string,
) => {
  const topic = payload.topic || payload.task.topic || payload.task.title || ''
  const compiledMarkdown = payload.compiledMarkdown || ''
  const rawSummary = payload.rawSummary || ''
  return [
    themeId,
    payload.task.id,
    payload.task.latest_modified_at || '',
    payload.task.video_url || '',
    payload.shareUrl || '',
    hashText(topic),
    hashText(compiledMarkdown),
    compiledMarkdown.length,
    hashText(rawSummary),
    rawSummary.length,
    settings.width,
    settings.layoutPreset,
    settings.metaMode,
    formatNumberKey(settings.fontScale),
    formatNumberKey(settings.contentPaddingScale),
  ].join('|')
}

const inferEffectivePixelRatio = (canvases: HTMLCanvasElement[], exportWidth: number) => {
  if (!canvases.length || exportWidth <= 0) return 0
  let minScale = Number.POSITIVE_INFINITY
  for (const canvas of canvases) {
    const scale = canvas.width / exportWidth
    if (Number.isFinite(scale) && scale > 0) {
      minScale = Math.min(minScale, scale)
    }
  }
  return Number.isFinite(minScale) ? minScale : 0
}

const DEFAULT_EXPORT_SETTINGS: SummaryImageExportSettings = {
  width: 1080,
  pixelRatio: 1.5,
  layoutPreset: 'mobile-9-16',
  metaMode: 'first-page-only',
  format: 'jpeg',
  quality: 88,
  targetSizeKB: 1400,
  fontScale: 1,
  contentPaddingScale: 1,
}

const waitNextFrame = () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
const waitMs = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

const waitForExportFonts = async () => {
  if (!('fonts' in document)) {
    return
  }

  const fontFaceSet = document.fonts
  const timeoutPromise = waitMs(1500)
  try {
    await Promise.race([
      fontFaceSet.ready,
      timeoutPromise,
    ])
    await Promise.allSettled([
      fontFaceSet.load(`400 16px ${EXPORT_FONT_FAMILY}`),
      fontFaceSet.load(`500 16px ${EXPORT_FONT_FAMILY}`),
      fontFaceSet.load(`600 16px ${EXPORT_FONT_FAMILY}`),
      fontFaceSet.load(`700 16px ${EXPORT_FONT_FAMILY}`),
    ])
  } catch {
    // Ignore font loading errors and let browser fallback apply.
  }
}

const clampNumber = (value: number, min: number, max: number, fallback: number) => {
  if (!Number.isFinite(value)) return fallback
  return Math.min(max, Math.max(min, value))
}

const sanitizeFilename = (name: string) => {
  return (name || 'summary')
    .replace(/[\\/:*?"<>|]+/g, '-')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 48) || 'summary'
}

const formatNowStamp = (date: Date) => {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}`
}

const toBlob = (canvas: HTMLCanvasElement, mimeType: string, quality?: number) => {
  return new Promise<Blob | null>((resolve) => {
    if (typeof quality === 'number') {
      canvas.toBlob(resolve, mimeType, quality)
      return
    }
    canvas.toBlob(resolve, mimeType)
  })
}

const blobToDataUrl = (blob: Blob) => {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      if (typeof reader.result === 'string') {
        resolve(reader.result)
      } else {
        reject(new Error('预览数据读取失败'))
      }
    }
    reader.onerror = () => reject(new Error('预览数据读取失败'))
    reader.readAsDataURL(blob)
  })
}

const mimeTypeByFormat: Record<SummaryImageFormat, string> = {
  png: 'image/png',
  jpeg: 'image/jpeg',
  webp: 'image/webp',
}

const extensionByFormat: Record<SummaryImageFormat, string> = {
  png: 'png',
  jpeg: 'jpg',
  webp: 'webp',
}

const formatToQuality = (quality: number) => {
  const normalized = clampNumber(quality, 50, 100, DEFAULT_EXPORT_SETTINGS.quality)
  return clampNumber(normalized / 100, JPEG_WEBP_MIN_QUALITY, JPEG_WEBP_MAX_QUALITY, 0.88)
}

const getLayoutAspectRatio = (preset: SummaryImageLayoutPreset): number | null => {
  if (preset === 'mobile-9-16') return 9 / 16
  if (preset === 'mobile-9-32') return 9 / 32
  if (preset === 'mobile-9-64') return 9 / 64
  return null
}

const normalizeSettings = (raw?: Partial<SummaryImageExportSettings>): SummaryImageExportSettings => {
  const merged: SummaryImageExportSettings = {
    ...DEFAULT_EXPORT_SETTINGS,
    ...raw,
  }

  const layoutPreset: SummaryImageLayoutPreset =
    merged.layoutPreset === 'mobile-9-16' ||
    merged.layoutPreset === 'mobile-9-32' ||
    merged.layoutPreset === 'mobile-9-64' ||
    merged.layoutPreset === 'long'
      ? merged.layoutPreset
      : DEFAULT_EXPORT_SETTINGS.layoutPreset
  const metaMode: SummaryImageMetaMode =
    merged.metaMode === 'all-pages' || merged.metaMode === 'first-page-only'
      ? merged.metaMode
      : DEFAULT_EXPORT_SETTINGS.metaMode

  const format: SummaryImageFormat =
    merged.format === 'png' || merged.format === 'webp' || merged.format === 'jpeg'
      ? merged.format
      : DEFAULT_EXPORT_SETTINGS.format

  return {
    width: Math.round(clampNumber(merged.width, 720, 1660, BASE_EXPORT_WIDTH)),
    pixelRatio: clampNumber(merged.pixelRatio, 1, 2.2, DEFAULT_EXPORT_SETTINGS.pixelRatio),
    layoutPreset,
    metaMode,
    format,
    quality: Math.round(clampNumber(merged.quality, 50, 100, DEFAULT_EXPORT_SETTINGS.quality)),
    targetSizeKB: Math.round(clampNumber(merged.targetSizeKB, 0, 8192, DEFAULT_EXPORT_SETTINGS.targetSizeKB)),
    fontScale: clampNumber(merged.fontScale, 0.8, 1.3, DEFAULT_EXPORT_SETTINGS.fontScale),
    contentPaddingScale: clampNumber(merged.contentPaddingScale, 0.8, 1.35, DEFAULT_EXPORT_SETTINGS.contentPaddingScale),
  }
}

const downloadBlob = (blob: Blob, filename: string) => {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

const createOffscreenHost = () => {
  const host = document.createElement('div')
  host.style.position = 'fixed'
  host.style.left = '-100000px'
  host.style.top = '0'
  host.style.background = 'transparent'
  host.style.zIndex = '-1'
  host.style.pointerEvents = 'none'
  host.style.padding = '0'
  document.body.appendChild(host)
  return host
}

const createScalePx = (fontScaleMultiplier: number) => {
  const scale = BASE_FONT_SCALE * fontScaleMultiplier
  return (basePx: number) => `${Math.round(basePx * scale * 10) / 10}px`
}

const restoreTimestampChipsToText = (root: HTMLElement) => {
  const chips = Array.from(root.querySelectorAll('.ss-time-jump-chip')) as HTMLElement[]

  for (const chip of chips) {
    const textContent = chip.textContent || ''
    // 匹配 HH:MM:SS 或 MM:SS 格式
    const timeMatch = textContent.match(/(\d{1,2}):(\d{2})(?::(\d{2}))?/)

    if (timeMatch) {
      const hh = timeMatch[3] ? timeMatch[1] : '00'
      const mm = timeMatch[3] ? timeMatch[2] : timeMatch[1]
      const ss = timeMatch[3] || timeMatch[2]
      const originalText = `（见 ${hh}:${mm}:${ss}）`
      const textNode = document.createTextNode(originalText)
      chip.replaceWith(textNode)
    }
  }
}

const applySummaryTypography = (
  summaryContent: HTMLElement,
  cleanedCompiledMarkdown: string,
  theme: MarkdownTheme,
  settings: SummaryImageExportSettings,
) => {
  summaryContent.className = 'prose prose-slate max-w-none ss-shared-prose markdown-theme-container ss-export-mode'
  summaryContent.style.maxWidth = '100%'
  summaryContent.innerHTML = cleanedCompiledMarkdown || '<p>暂无总结内容</p>'

  restoreTimestampChipsToText(summaryContent)

  applySummaryTypographyStyles(summaryContent, theme, settings)

  const exportConfig = theme.exportConfig
  const baseFontSize = (exportConfig?.fontSize || SUMMARY_FONT_SIZE) * settings.fontScale
  console.log('[Summary Typography] Base font size for body text:', baseFontSize, 'px')
}

const applySummaryTypographyStyles = (
  summaryContent: HTMLElement,
  theme: MarkdownTheme,
  settings: SummaryImageExportSettings,
) => {
  summaryContent.className = 'prose prose-slate max-w-none ss-shared-prose markdown-theme-container ss-export-mode'

  const exportConfig = theme.exportConfig
  const baseFontSize = (exportConfig?.fontSize || SUMMARY_FONT_SIZE) * settings.fontScale
  const baseLineHeight = exportConfig?.lineHeight || SUMMARY_LINE_HEIGHT

  const normalizedBaseSize = `${Math.round(baseFontSize * 10) / 10}px`
  summaryContent.style.maxWidth = '100%'
  summaryContent.style.fontSize = normalizedBaseSize
  summaryContent.style.lineHeight = String(baseLineHeight)
  summaryContent.style.fontFamily = EXPORT_FONT_FAMILY
  summaryContent.style.setProperty('--md-base-font-size', normalizedBaseSize)
  summaryContent.style.setProperty('--md-base-line-height', String(baseLineHeight))

  const bodyNodes = summaryContent.querySelectorAll('p, li, blockquote, td, th, figcaption') as NodeListOf<HTMLElement>
  bodyNodes.forEach((el) => {
    el.style.fontSize = normalizedBaseSize
    el.style.lineHeight = String(baseLineHeight)
  })

  const headingScale = exportConfig?.headingScale
  const titleScale = baseFontSize / BASE_REFERENCE_FONT_SIZE
  const scaledHeadingPx = (basePx: number) => `${Math.round(basePx * titleScale * 10) / 10}px`

  if (headingScale) {
    const headings: Array<keyof typeof headingScale> = ['h1', 'h2', 'h3', 'h4']
    headings.forEach((tag) => {
      const scale = headingScale[tag]
      if (!scale) return
      const nodes = summaryContent.querySelectorAll(tag) as NodeListOf<HTMLElement>
      nodes.forEach((el) => {
        el.style.fontSize = scaledHeadingPx(scale)
        el.style.lineHeight = '1.3'
      })
    })
  } else {
    const summaryH1Nodes = summaryContent.querySelectorAll('h1') as NodeListOf<HTMLElement>
    summaryH1Nodes.forEach((el) => {
      el.style.fontSize = scaledHeadingPx(34)
      el.style.lineHeight = '1.28'
    })

    const summaryH2Nodes = summaryContent.querySelectorAll('h2') as NodeListOf<HTMLElement>
    summaryH2Nodes.forEach((el) => {
      el.style.fontSize = scaledHeadingPx(29)
      el.style.lineHeight = '1.32'
    })

    const summaryH3Nodes = summaryContent.querySelectorAll('h3') as NodeListOf<HTMLElement>
    summaryH3Nodes.forEach((el) => {
      el.style.fontSize = scaledHeadingPx(24)
      el.style.lineHeight = '1.36'
    })

    const summaryH4Nodes = summaryContent.querySelectorAll('h4') as NodeListOf<HTMLElement>
    summaryH4Nodes.forEach((el) => {
      el.style.fontSize = scaledHeadingPx(20)
      el.style.lineHeight = '1.4'
    })
  }
}

const createPageCard = (
  payload: SummaryImageExportPayload,
  convertedAt: Date,
  theme: MarkdownTheme,
  settings: SummaryImageExportSettings,
  includeMeta: boolean,
): RenderPageContext => {
  const shareUrl = payload.shareUrl || DEFAULT_SHARE_URL
  const cleanedRawSummary = stripDoubleBracePlaceholders(payload.rawSummary || '')
  const scalePx = createScalePx(settings.fontScale)

  const headerHorizontalPadding = Math.round(HEADER_HORIZONTAL_PADDING * settings.contentPaddingScale)
  const contentHorizontalPadding = Math.round(CONTENT_HORIZONTAL_PADDING * settings.contentPaddingScale)
  const contentTopPadding = Math.round(CONTENT_TOP_PADDING * settings.contentPaddingScale)
  const contentBottomPadding = Math.round(CONTENT_BOTTOM_PADDING * settings.contentPaddingScale)

  const card = document.createElement('section')
  card.style.width = `${settings.width}px`
  card.style.background = '#ffffff'
  card.style.border = '1px solid #e2e8f0'
  card.style.borderRadius = `${Math.round(24 * settings.contentPaddingScale)}px`
  card.style.boxShadow = '0 16px 40px rgba(15, 23, 42, 0.08)'
  card.style.overflow = 'hidden'
  card.style.fontFamily = EXPORT_FONT_FAMILY

  let header: HTMLDivElement | null = null
  if (includeMeta) {
    header = document.createElement('div')
    header.style.padding = `${Math.round(48 * settings.contentPaddingScale)}px ${headerHorizontalPadding}px ${Math.round(40 * settings.contentPaddingScale)}px`
    header.style.background = 'linear-gradient(180deg, #f7faff 0%, #fdfdff 100%)'
    header.style.borderBottom = '1px solid #e2e8f0'

    const title = document.createElement('h1')
    title.textContent = payload.topic || payload.task.title || 'AI 总结'
    title.style.margin = `0 0 ${Math.round(16 * settings.contentPaddingScale)}px`
    title.style.fontSize = scalePx(36)
    title.style.lineHeight = '1.35'
    title.style.fontWeight = '700'
    title.style.color = '#0f172a'
    title.style.letterSpacing = '-0.01em'

    const videoLinkRow = document.createElement('div')
    videoLinkRow.style.display = 'flex'
    videoLinkRow.style.alignItems = 'center'
    videoLinkRow.style.gap = '6px'
    videoLinkRow.style.marginBottom = `${Math.round(28 * settings.contentPaddingScale)}px`
    videoLinkRow.style.fontSize = scalePx(13)
    videoLinkRow.style.color = '#64748b'

    const videoLinkLabel = document.createElement('span')
    videoLinkLabel.textContent = '视频链接:'
    videoLinkLabel.style.color = '#94a3b8'
    videoLinkLabel.style.whiteSpace = 'nowrap'

    const videoLinkValue = document.createElement('span')
    videoLinkValue.textContent = payload.task.video_url || '--'
    videoLinkValue.style.color = '#64748b'
    videoLinkValue.style.wordBreak = 'break-all'
    videoLinkValue.style.lineHeight = '1.4'

    videoLinkRow.append(videoLinkLabel, videoLinkValue)

    const authorName = (payload.task.author_name || '').trim()
    if (authorName) {
      const authorPrefix = document.createElement('span')
      authorPrefix.textContent = 'By'
      authorPrefix.style.color = '#94a3b8'
      authorPrefix.style.whiteSpace = 'nowrap'

      const authorValue = document.createElement(payload.task.author_url ? 'a' : 'span')
      authorValue.textContent = authorName
      authorValue.style.color = '#64748b'
      authorValue.style.wordBreak = 'break-all'
      authorValue.style.lineHeight = '1.4'
      if (payload.task.author_url) {
        authorValue.setAttribute('href', payload.task.author_url)
        authorValue.setAttribute('target', '_blank')
        authorValue.style.textDecoration = 'underline'
        authorValue.style.textUnderlineOffset = '2px'
      }

      videoLinkRow.append(authorPrefix, authorValue)
    }

    const ratio = formatConversionRatio(payload.task.audio_duration, payload.task.transcription_time)

    const metaCard = document.createElement('div')
    metaCard.style.display = 'flex'
    metaCard.style.flexDirection = 'column'
    metaCard.style.gap = `${Math.round(16 * settings.contentPaddingScale)}px`

    const metaRow1 = document.createElement('div')
    metaRow1.style.display = 'flex'
    metaRow1.style.alignItems = 'center'
    metaRow1.style.gap = `${Math.round(32 * settings.contentPaddingScale)}px`
    metaRow1.style.fontSize = scalePx(14)
    metaRow1.style.color = '#64748b'

    const durationItem = document.createElement('span')
    durationItem.innerHTML = `视频时长 <strong style="color: #334155; font-weight: 600;">${formatDuration(payload.task.audio_duration)}</strong>`
    const transcriptionItem = document.createElement('span')
    transcriptionItem.innerHTML = `转录耗时 <strong style="color: #334155; font-weight: 600;">${formatTranscriptionDuration(payload.task.transcription_time)}</strong>`
    const ratioItem = document.createElement('span')
    ratioItem.innerHTML = `转换比 <strong style="color: #334155; font-weight: 600;">${ratio}x</strong>`

    metaRow1.append(durationItem, transcriptionItem, ratioItem)

    const metaRow2 = document.createElement('div')
    metaRow2.style.display = 'flex'
    metaRow2.style.alignItems = 'center'
    metaRow2.style.gap = `${Math.round(32 * settings.contentPaddingScale)}px`
    metaRow2.style.fontSize = scalePx(14)
    metaRow2.style.color = '#64748b'

    const wordsItem = document.createElement('span')
    wordsItem.innerHTML = `总字数 <strong style="color: #334155; font-weight: 600;">${countWords(cleanedRawSummary)}</strong>`
    const timeItem = document.createElement('span')
    timeItem.innerHTML = `生成时间 <strong style="color: #334155; font-weight: 600;">${formatDateTime(convertedAt)}</strong>`

    metaRow2.append(wordsItem, timeItem)
    metaCard.append(metaRow1, metaRow2)
    header.append(title, videoLinkRow, metaCard)
  }

  const contentWrap = document.createElement('div')
  contentWrap.style.padding = `${contentTopPadding}px ${contentHorizontalPadding}px ${contentBottomPadding}px`
  contentWrap.style.color = theme.cssVariables['--md-text-color'] || '#334155'

  const summaryContent = document.createElement('article')
  summaryContent.className = 'prose prose-slate max-w-none ss-shared-prose markdown-theme-container ss-export-mode'
  contentWrap.appendChild(summaryContent)

  const footer = document.createElement('div')
  footer.style.padding = `${Math.round(24 * settings.contentPaddingScale)}px ${contentHorizontalPadding}px ${Math.round(28 * settings.contentPaddingScale)}px`
  footer.style.borderTop = '1px solid #eef2f7'
  footer.style.fontSize = scalePx(13)
  footer.style.color = '#94a3b8'
  footer.style.display = 'flex'
  footer.style.flexDirection = 'column'
  footer.style.alignItems = 'center'
  footer.style.gap = '6px'
  footer.style.textAlign = 'center'
  footer.style.background = '#ffffff'

  const footerMainRow = document.createElement('div')
  footerMainRow.style.display = 'flex'
  footerMainRow.style.alignItems = 'center'
  footerMainRow.style.justifyContent = 'center'
  footerMainRow.style.gap = '8px'

  const aiIcon = document.createElement('span')
  aiIcon.textContent = '✨'
  aiIcon.style.fontSize = scalePx(16)

  const footerMainText = document.createElement('span')
  footerMainText.textContent = '由 ShengWen 智能总结'
  footerMainText.style.color = '#a7b6ca'

  const footerProjectRow = document.createElement('div')
  footerProjectRow.style.display = 'flex'
  footerProjectRow.style.alignItems = 'center'
  footerProjectRow.style.justifyContent = 'center'
  footerProjectRow.style.gap = '4px'
  footerProjectRow.style.flexWrap = 'wrap'

  const footerProjectLabel = document.createElement('span')
  footerProjectLabel.textContent = '项目:'
  footerProjectLabel.style.color = '#a7b6ca'

  const footerProjectLink = document.createElement('span')
  footerProjectLink.textContent = shareUrl
  footerProjectLink.style.color = '#7c97bc'
  footerProjectLink.style.textDecoration = 'underline'
  footerProjectLink.style.textUnderlineOffset = '2px'
  footerProjectLink.style.wordBreak = 'break-all'

  footerMainRow.append(aiIcon, footerMainText)
  footerProjectRow.append(footerProjectLabel, footerProjectLink)
  footer.append(footerMainRow, footerProjectRow)

  if (header) {
    card.append(header, contentWrap, footer)
  } else {
    card.append(contentWrap, footer)
  }

  return {
    card,
    summaryContent,
  }
}

const resolveMermaidFontSizePx = (
  theme: MarkdownTheme,
  settings: SummaryImageExportSettings,
) => {
  const exportConfig = theme.exportConfig
  const baseFontSize = (exportConfig?.fontSize || SUMMARY_FONT_SIZE) * settings.fontScale
  const mermaidFontSize = Math.round(clampNumber(baseFontSize * MERMAID_FONT_RATIO, 12, 22, 16) * 10) / 10

  console.log('[Mermaid Font Debug] Base font size:', baseFontSize)
  console.log('[Mermaid Font Debug] MERMAID_FONT_RATIO:', MERMAID_FONT_RATIO)
  console.log('[Mermaid Font Debug] Calculated mermaid font size:', mermaidFontSize)

  return mermaidFontSize
}

const renderMermaidInNode = async (node: HTMLElement, mermaidFontSizePx: number) => {
  normalizeAccidentalInlineCodeBlocks(node)

  const mermaidNodes = Array.from(node.querySelectorAll('.mermaid')) as HTMLElement[]
  if (!mermaidNodes.length) return

  const mermaid = await getMermaid()

  // 使用和前端一致的主题配置，只额外添加 fontSize
  const customTheme = {
    primaryColor: '#dbeafe',
    primaryTextColor: '#0f172a',
    primaryBorderColor: '#3b82f6',
    lineColor: '#334155',
    secondaryColor: '#f8fafc',
    tertiaryColor: '#eff6ff',
    clusterBkg: '#f8fafc',
    clusterBorder: '#cbd5e1',
    edgeLabelBackground: '#ffffff',
    fontFamily: EXPORT_FONT_FAMILY,
    fontSize: `${mermaidFontSizePx}px`,
  }

  mermaid.initialize({
    startOnLoad: false,
    suppressErrorRendering: true,
    theme: 'base',
    themeVariables: customTheme,
    securityLevel: 'loose',
    flowchart: {
      htmlLabels: false,
      curve: 'basis',
    },
    themeCSS: `
      .mermaid .node rect, .mermaid .node circle, .mermaid .node ellipse, .mermaid .node polygon, .mermaid .node path {
        fill: #dbeafe;
        stroke: #3b82f6;
        stroke-width: 2px;
        rx: 10px;
        ry: 10px;
      }
      .mermaid .node:hover rect, .mermaid .node:hover circle, .mermaid .node:hover ellipse, .mermaid .node:hover polygon, .mermaid .node:hover path {
        fill: #bfdbfe;
      }
      .mermaid .edgePath path {
        stroke: #334155;
        stroke-width: 2px;
        fill: none;
      }
      .mermaid .cluster rect {
        fill: #f8fafc;
        stroke: #cbd5e1;
        stroke-width: 2px;
        stroke-dasharray: 5, 5;
        rx: 12px;
      }
      .mermaid text {
        fill: #0f172a;
        font-family: ${EXPORT_FONT_FAMILY};
        font-weight: 500;
        font-size: ${mermaidFontSizePx}px;
      }
      .mermaid .label {
        color: #0f172a;
      }
      .mermaid .error-icon {
        fill: #dc2626;
      }
      .mermaid .error-text {
        fill: #7f1d1d;
        stroke: #7f1d1d;
      }
      .mermaid .error-message {
        color: #7f1d1d;
      }
    `,
  } as any)

  for (const el of mermaidNodes) {
    try {
      const code = el.textContent || ''
      el.removeAttribute('data-processed')
      el.innerHTML = ''

      const mermaid = await getMermaid()
      const renderId = `mermaid-export-${Date.now()}-${Math.floor(Math.random() * 1000000)}`
      const result = await mermaid.render(renderId, code)
      el.innerHTML = result.svg

      const svg = el.querySelector('svg')
      if (svg) {
        // 修复 SVG 布局，避免裁切
        normalizeMermaidSvgLayout(el)

        // 强制设置所有文本元素的字体大小
        const allTextElements = svg.querySelectorAll('text, tspan, foreignObject div, foreignObject span, foreignObject p')
        allTextElements.forEach((textEl) => {
          if (textEl instanceof SVGElement) {
            textEl.setAttribute('font-size', `${mermaidFontSizePx}`)
            textEl.style.setProperty('font-size', `${mermaidFontSizePx}px`, 'important')
          } else if (textEl instanceof HTMLElement) {
            textEl.style.setProperty('font-size', `${mermaidFontSizePx}px`, 'important')
          }
        })

        // 在 SVG 中注入全局样式覆盖
        const styleEl = document.createElementNS('http://www.w3.org/2000/svg', 'style')
        styleEl.textContent = `
          text, tspan { font-size: ${mermaidFontSizePx}px !important; }
          foreignObject div, foreignObject span, foreignObject p { font-size: ${mermaidFontSizePx}px !important; }
        `
        svg.insertBefore(styleEl, svg.firstChild)
      }
    } catch (err) {
      console.warn('Mermaid render failed:', err)
      el.remove()
    }
  }

  await waitNextFrame()
}

const cloneSummaryBlocks = async (
  payload: SummaryImageExportPayload,
  theme: MarkdownTheme,
  settings: SummaryImageExportSettings,
): Promise<HTMLElement[]> => {
  const source = document.createElement('article')
  const cleanedCompiledMarkdown = stripDoubleBracePlaceholders(payload.compiledMarkdown || '')
  applySummaryTypography(source, cleanedCompiledMarkdown, theme, settings)
  await renderMermaidInNode(source, resolveMermaidFontSizePx(theme, settings))
  applySummaryTypographyStyles(source, theme, settings)
  normalizeExportListMarkers(source)
  normalizeExportQuoteBaseline(source)

  const blocks = Array.from(source.children).map((node) => node.cloneNode(true) as HTMLElement)
  if (!blocks.length) {
    const empty = document.createElement('p')
    empty.textContent = '暂无总结内容'
    blocks.push(empty)
  }
  return blocks
}

const createScaledBlockWrapper = (block: HTMLElement, scale: number, naturalHeight: number) => {
  const wrapper = document.createElement('div')
  wrapper.style.height = `${Math.ceil(naturalHeight * scale)}px`
  wrapper.style.overflow = 'hidden'
  wrapper.style.margin = '0'

  const inner = document.createElement('div')
  inner.style.transform = `scale(${scale})`
  inner.style.transformOrigin = 'top left'
  inner.style.width = `${100 / scale}%`
  inner.style.display = 'flow-root'
  inner.appendChild(block)

  wrapper.appendChild(inner)
  return wrapper
}

const formatOrderedMarker = (value: number, type: string) => {
  const normalized = Math.max(1, Math.floor(value))

  const toAlpha = (n: number, upper: boolean) => {
    let num = n
    let out = ''
    while (num > 0) {
      num -= 1
      out = String.fromCharCode((num % 26) + (upper ? 65 : 97)) + out
      num = Math.floor(num / 26)
    }
    return out || (upper ? 'A' : 'a')
  }

  const toRoman = (n: number, upper: boolean) => {
    const map: Array<[number, string]> = [
      [1000, 'M'], [900, 'CM'], [500, 'D'], [400, 'CD'],
      [100, 'C'], [90, 'XC'], [50, 'L'], [40, 'XL'],
      [10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I'],
    ]
    let remain = n
    let out = ''
    for (const [num, sym] of map) {
      while (remain >= num) {
        out += sym
        remain -= num
      }
    }
    return upper ? out : out.toLowerCase()
  }

  if (type === 'a') return `${toAlpha(normalized, false)}.`
  if (type === 'A') return `${toAlpha(normalized, true)}.`
  if (type === 'i') return `${toRoman(normalized, false)}.`
  if (type === 'I') return `${toRoman(normalized, true)}.`
  return `${normalized}.`
}

const normalizeExportListMarkers = (root: HTMLElement) => {
  const lists = Array.from(root.querySelectorAll('ul, ol')) as Array<HTMLUListElement | HTMLOListElement>

  for (const list of lists) {
    const liNodes = Array.from(list.children).filter((el) => el.tagName === 'LI') as HTMLLIElement[]
    if (!liNodes.length) continue

    const isOrdered = list.tagName === 'OL'
    const orderedType = isOrdered ? ((list as HTMLOListElement).type || '1') : '1'
    const hasReversed = isOrdered && list.hasAttribute('reversed')
    const startAttrRaw = isOrdered ? (list as HTMLOListElement).getAttribute('start') : null
    const parsedStart = startAttrRaw ? Number(startAttrRaw) : Number.NaN
    const start = Number.isFinite(parsedStart)
      ? Math.max(1, Math.floor(parsedStart))
      : (hasReversed ? liNodes.length : 1)

    for (const [index, li] of liNodes.entries()) {
      if (li.classList.contains('ss-export-list-item')) continue

      const markerText = isOrdered
        ? formatOrderedMarker(hasReversed ? start - index : start + index, orderedType)
        : '•'

      const marker = document.createElement('span')
      marker.className = 'ss-export-list-marker'
      marker.textContent = markerText

      const body = document.createElement('div')
      body.className = 'ss-export-list-body'
      while (li.firstChild) {
        body.appendChild(li.firstChild)
      }

      li.classList.add('ss-export-list-item')
      li.append(marker, body)
    }
  }
}

const normalizeExportQuoteBaseline = (root: HTMLElement) => {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const textNodes: Text[] = []

  while (walker.nextNode()) {
    const node = walker.currentNode as Text
    const parent = node.parentElement
    if (!parent) continue
    if (parent.closest('pre, code, svg, .mermaid')) continue

    const raw = node.nodeValue || ''
    if (!/[“”‘’]/.test(raw)) continue
    textNodes.push(node)
  }

  for (const textNode of textNodes) {
    const raw = textNode.nodeValue || ''
    const fragment = document.createDocumentFragment()
    let lastIndex = 0
    EXPORT_QUOTE_CHARS_RE.lastIndex = 0

    let match = EXPORT_QUOTE_CHARS_RE.exec(raw)
    while (match) {
      const index = match.index
      if (index > lastIndex) {
        fragment.appendChild(document.createTextNode(raw.slice(lastIndex, index)))
      }

      const span = document.createElement('span')
      span.className = 'ss-export-cjk-quote'
      span.textContent = match[0]
      fragment.appendChild(span)

      lastIndex = index + match[0].length
      match = EXPORT_QUOTE_CHARS_RE.exec(raw)
    }

    if (lastIndex < raw.length) {
      fragment.appendChild(document.createTextNode(raw.slice(lastIndex)))
    }

    textNode.replaceWith(fragment)
  }
}

const appendOversizedBlock = (
  page: RenderPageContext,
  block: HTMLElement,
  standardPageHeight: number,
) => {
  const baseHeight = page.card.scrollHeight
  page.summaryContent.appendChild(block)
  const fullHeight = page.card.scrollHeight
  page.summaryContent.removeChild(block)

  const naturalHeight = Math.max(1, fullHeight - baseHeight)
  const availableHeight = Math.max(48, standardPageHeight - baseHeight)
  let scale = clampNumber(availableHeight / naturalHeight, OVERSIZE_MIN_SCALE, 1, 1)

  let wrapper = createScaledBlockWrapper(block, scale, naturalHeight)
  page.summaryContent.appendChild(wrapper)

  while (page.card.scrollHeight > standardPageHeight && scale > OVERSIZE_MIN_SCALE + 0.01) {
    page.summaryContent.removeChild(wrapper)
    scale = Math.max(OVERSIZE_MIN_SCALE, scale - 0.05)
    wrapper = createScaledBlockWrapper(block.cloneNode(true) as HTMLElement, scale, naturalHeight)
    page.summaryContent.appendChild(wrapper)
    if (scale <= OVERSIZE_MIN_SCALE) break
  }
}

const paginateSummaryBlocks = (
  blocks: HTMLElement[],
  payload: SummaryImageExportPayload,
  theme: MarkdownTheme,
  settings: SummaryImageExportSettings,
  convertedAt: Date,
  host: HTMLElement,
  standardPageHeight: number | null,
): RenderPageContext[] => {
  const pages: RenderPageContext[] = []
  let pageIndex = 0

  const createPage = () => {
    const page = createPageCard(
      payload,
      convertedAt,
      theme,
      settings,
      settings.metaMode === 'all-pages' || pageIndex === 0,
    )
    host.appendChild(page.card)
    pageIndex += 1
    return page
  }

  if (!standardPageHeight) {
    const page = createPage()
    blocks.forEach((block) => {
      page.summaryContent.appendChild(block.cloneNode(true) as HTMLElement)
    })
    pages.push(page)
    return pages
  }

  let currentPage = createPage()

  for (const block of blocks) {
    const candidate = block.cloneNode(true) as HTMLElement
    currentPage.summaryContent.appendChild(candidate)

    if (currentPage.card.scrollHeight <= standardPageHeight) {
      continue
    }

    currentPage.summaryContent.removeChild(candidate)

    if (currentPage.summaryContent.children.length === 0) {
      appendOversizedBlock(currentPage, candidate, standardPageHeight)
      pages.push(currentPage)
      currentPage = createPage()
      continue
    }

    pages.push(currentPage)
    currentPage = createPage()

    const retry = block.cloneNode(true) as HTMLElement
    currentPage.summaryContent.appendChild(retry)
    if (currentPage.card.scrollHeight > standardPageHeight) {
      currentPage.summaryContent.removeChild(retry)
      appendOversizedBlock(currentPage, retry, standardPageHeight)
    }
  }

  if (currentPage.summaryContent.children.length > 0 || pages.length === 0) {
    pages.push(currentPage)
  } else {
    currentPage.card.remove()
  }

  return pages
}

const captureNode = async (
  node: HTMLElement,
  html2canvasFn: typeof html2canvas,
  pixelRatio: number,
  exportWidth: number,
) => {
  await waitNextFrame()
  return html2canvasFn(node, {
    backgroundColor: '#f8faff',
    scale: pixelRatio,
    useCORS: true,
    logging: false,
    windowWidth: exportWidth,
    windowHeight: Math.max(1200, node.scrollHeight + 80),
  })
}

const getCaptureScaleCandidates = (preferredScale: number, isPreview: boolean) => {
  if (isPreview) {
    const capped = Math.min(preferredScale, PREVIEW_PIXEL_RATIO_CAP)
    if (capped > 1.2) {
      return [capped, 1.2, 1]
    }
    return [capped, 1]
  }
  return [preferredScale, Math.max(1, preferredScale - 0.35), 1]
}

const captureWithFallback = async (
  card: HTMLElement,
  html2canvasFn: typeof html2canvas,
  settings: SummaryImageExportSettings,
  isPreview: boolean,
) => {
  let lastError: unknown = null
  const scaleCandidates = getCaptureScaleCandidates(settings.pixelRatio, isPreview)

  for (const scale of scaleCandidates) {
    try {
      return await captureNode(card, html2canvasFn, scale, settings.width)
    } catch (error) {
      lastError = error
    }
  }

  throw lastError instanceof Error ? lastError : new Error('图片捕获失败')
}

const encodeCanvasBySettings = async (
  source: HTMLCanvasElement,
  settings: SummaryImageExportSettings,
  isPreview: boolean,
) => {
  const mimeType = mimeTypeByFormat[settings.format]
  const targetBytes = settings.targetSizeKB > 0 ? settings.targetSizeKB * 1024 : 0

  const qualityCandidates = settings.format === 'png'
    ? [undefined]
    : (() => {
      const base = formatToQuality(settings.quality)
      const step = isPreview ? 0.09 : 0.06
      const limit = isPreview ? 3 : 8
      const values: number[] = [base]
      for (let i = 1; i <= limit; i += 1) {
        values.push(clampNumber(base - step * i, JPEG_WEBP_MIN_QUALITY, JPEG_WEBP_MAX_QUALITY, JPEG_WEBP_MIN_QUALITY))
      }
      return values
    })()

  let bestBlob: Blob | null = null
  for (const quality of qualityCandidates) {
    const blob = await toBlob(source, mimeType, quality)
    if (!blob) continue

    if (!bestBlob || blob.size < bestBlob.size) {
      bestBlob = blob
    }

    if (targetBytes === 0 || blob.size <= targetBytes) {
      return { blob, canvas: source }
    }
  }

  if (bestBlob) {
    return { blob: bestBlob, canvas: source }
  }

  throw new Error('图片编码失败')
}

const buildPageCanvases = async (
  payload: SummaryImageExportPayload,
  settings: SummaryImageExportSettings,
  isPreview: boolean,
): Promise<HTMLCanvasElement[]> => {
  const html2canvasFn = html2canvas
  await waitForExportFonts()
  const now = new Date()
  const currentTheme = getCurrentTheme()
  const standardPageHeight = (() => {
    const aspectRatio = getLayoutAspectRatio(settings.layoutPreset)
    if (!aspectRatio) return null
    return Math.round(settings.width / aspectRatio)
  })()

  const host = createOffscreenHost()

  try {
    const blocks = await cloneSummaryBlocks(payload, currentTheme, settings)
    const pages = paginateSummaryBlocks(blocks, payload, currentTheme, settings, now, host, standardPageHeight)

    const canvases: HTMLCanvasElement[] = []

    for (const [index, page] of pages.entries()) {
      if (standardPageHeight && index < pages.length - 1) {
        page.card.style.height = `${standardPageHeight}px`
      } else {
        page.card.style.height = 'auto'
      }

      const canvas = await captureWithFallback(page.card, html2canvasFn, settings, isPreview)
      canvases.push(canvas)
    }

    return canvases
  } finally {
    host.remove()
  }
}

export const createDefaultSummaryImageExportSettings = (): SummaryImageExportSettings => ({
  ...DEFAULT_EXPORT_SETTINGS,
})

export function useSummaryImageExporter() {
  let renderCanvasCache: RenderCanvasCacheEntry | null = null

  const getReusableCanvases = (
    payload: SummaryImageExportPayload,
    settings: SummaryImageExportSettings,
  ): HTMLCanvasElement[] | null => {
    const themeId = getCurrentTheme().id || 'default'
    const signature = createRenderSignature(payload, settings, themeId)
    if (!renderCanvasCache || renderCanvasCache.signature !== signature) {
      return null
    }
    if (renderCanvasCache.effectivePixelRatio + REUSE_PIXEL_RATIO_EPSILON < settings.pixelRatio) {
      return null
    }
    return renderCanvasCache.canvases
  }

  const rememberRenderedCanvases = (
    payload: SummaryImageExportPayload,
    settings: SummaryImageExportSettings,
    canvases: HTMLCanvasElement[],
  ) => {
    const themeId = getCurrentTheme().id || 'default'
    renderCanvasCache = {
      signature: createRenderSignature(payload, settings, themeId),
      effectivePixelRatio: inferEffectivePixelRatio(canvases, settings.width),
      canvases,
    }
  }

  const generateSummaryImagePreview = async (
    payload: SummaryImageExportPayload,
    customSettings?: Partial<SummaryImageExportSettings>,
    onProgress?: SummaryImageProgressCallback,
  ): Promise<SummaryImagePreviewResult> => {
    const normalized = normalizeSettings(customSettings)
    const previewSettings: SummaryImageExportSettings = {
      ...normalized,
      pixelRatio: Math.min(normalized.pixelRatio, PREVIEW_PIXEL_RATIO_CAP),
    }

    const reusedCanvases = getReusableCanvases(payload, previewSettings)
    const canvases = reusedCanvases || await buildPageCanvases(payload, previewSettings, true)
    if (!reusedCanvases) {
      rememberRenderedCanvases(payload, previewSettings, canvases)
    }
    const pages: SummaryImagePreviewPage[] = []
    let totalBytes = 0
    const total = canvases.length

    for (const [index, canvas] of canvases.entries()) {
      if (onProgress) {
        onProgress({ current: index + 1, total, page: null })
      }

      const { blob } = await encodeCanvasBySettings(canvas, normalized, true)
      const dataUrl = await blobToDataUrl(blob)
      totalBytes += blob.size

      const page: SummaryImagePreviewPage = {
        index,
        dataUrl,
        width: canvas.width,
        height: canvas.height,
        sizeKB: Math.round(blob.size / 1024),
        format: normalized.format,
      }

      pages.push(page)

      if (onProgress) {
        onProgress({ current: index + 1, total, page })
      }
    }

    return {
      pages,
      totalSizeKB: Math.round(totalBytes / 1024),
      format: normalized.format,
    }
  }

  const exportSummaryAsImage = async (
    payload: SummaryImageExportPayload,
    customSettings?: Partial<SummaryImageExportSettings>,
  ): Promise<SummaryImageExportResult> => {
    const normalized = normalizeSettings(customSettings)
    const now = new Date()
    const fileBase = sanitizeFilename(payload.topic || payload.task.title || 'summary')
    const stamp = formatNowStamp(now)
    const extension = extensionByFormat[normalized.format]

    const reusedCanvases = getReusableCanvases(payload, normalized)
    const canvases = reusedCanvases || await buildPageCanvases(payload, normalized, false)
    if (!reusedCanvases) {
      rememberRenderedCanvases(payload, normalized, canvases)
    }

    const pageResults: SummaryImageExportPageResult[] = []
    const filenames: string[] = []
    let totalBytes = 0
    const hasMultiplePages = canvases.length > 1
    const pageNumberWidth = Math.max(2, String(canvases.length).length)

    for (const [index, canvas] of canvases.entries()) {
      const { blob } = await encodeCanvasBySettings(canvas, normalized, false)
      totalBytes += blob.size

      const pagePrefix = hasMultiplePages ? `${String(index + 1).padStart(pageNumberWidth, '0')}-` : ''
      const filename = `${pagePrefix}${fileBase}-summary-${stamp}.${extension}`
      downloadBlob(blob, filename)

      filenames.push(filename)
      pageResults.push({
        index,
        filename,
        width: canvas.width,
        height: canvas.height,
        sizeKB: Math.round(blob.size / 1024),
      })

      if (hasMultiplePages) {
        await waitMs(DOWNLOAD_GAP_MS)
      }
    }

    return {
      files: pageResults.length,
      mode: pageResults.length > 1 ? 'multi' : 'single',
      totalSizeKB: Math.round(totalBytes / 1024),
      format: normalized.format,
      filenames,
      pages: pageResults,
    }
  }

  return {
    exportSummaryAsImage,
    generateSummaryImagePreview,
    createDefaultSummaryImageExportSettings,
  }
}

