import { ref, onMounted, onUnmounted } from 'vue'
import axios from 'axios'
import type {
  Task,
  CreateTaskRequest,
  SummaryMode,
  VideoQuality,
  LLMProvider,
  LLMSettings,
  UpdateLLMSettingsRequest,
  TranscriptionSettings,
  UpdateTranscriptionSettingsRequest,
  SummarizationSettings,
  UpdateSummarizationSettingsRequest,
  BilibiliCookieFromBrowserResult,
  BilibiliVideoInfo,
  BilibiliPartsConfig
} from '../types'

// 传统复制方法（兼容非安全上下文，如局域网 HTTP）
const fallbackCopyToClipboard = (text: string): boolean => {
  const textarea = document.createElement('textarea')
  textarea.value = text

  // 设置样式使其不可见但仍可操作
  textarea.style.position = 'fixed'
  textarea.style.top = '0'
  textarea.style.left = '0'
  textarea.style.width = '2em'
  textarea.style.height = '2em'
  textarea.style.padding = '0'
  textarea.style.border = 'none'
  textarea.style.outline = 'none'
  textarea.style.boxShadow = 'none'
  textarea.style.background = 'transparent'
  textarea.style.opacity = '0'

  document.body.appendChild(textarea)

  try {
    // 选中文本
    textarea.focus()
    textarea.select()
    textarea.setSelectionRange(0, text.length)

    // 执行复制命令
    const success = document.execCommand('copy')

    return success
  } finally {
    // 清理 DOM
    document.body.removeChild(textarea)
  }
}

const extractFirstUrl = (raw: string): string | null => {
  const text = (raw || '').trim()
  if (!text) return null

  const directMatch = text.match(/https?:\/\/[^\s]+/i)
  let candidate = directMatch?.[0] || ''

  if (!candidate) {
    const domainMatch = text.match(/((?:www\.)?(?:b23\.tv|bilibili\.com|youtube\.com|youtu\.be)\/[^\s]+)/i)
    if (!domainMatch?.[1]) return null
    candidate = `https://${domainMatch[1]}`
  }

  candidate = candidate.replace(/[)\]}>，。！？；：”’】）》]+$/g, '')

  try {
    return new URL(candidate).toString()
  } catch {
    return null
  }
}

const isBilibiliUrl = (url: string): boolean => {
  try {
    const hostname = new URL(url).hostname.toLowerCase()
    return hostname.includes('bilibili.com') || hostname.includes('b23.tv')
  } catch {
    return false
  }
}

const getAxiosErrorMessage = (err: unknown, fallback: string): string => {
  if (!axios.isAxiosError(err)) return fallback

  const detail = err.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) {
    return detail
  }

  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0]
    if (first && typeof first === 'object' && 'msg' in first) {
      const message = String((first as { msg?: unknown }).msg || '').trim()
      if (message) {
        return `请求参数错误：${message}`
      }
    }
  }

  return err.message ? `${fallback}：${err.message}` : fallback
}

const isCanceledRequest = (err: unknown): boolean => {
  if (axios.isCancel(err)) return true
  if (!axios.isAxiosError(err)) return false
  return err.code === 'ERR_CANCELED'
}

export function useTaskViewModel() {
  const normalizeBase = (base?: string) => (base || '').trim().replace(/\/+$/, '')
  const isLoopbackHost = (host: string) => {
    const normalized = (host || '').trim().toLowerCase()
    return normalized === 'localhost' || normalized === '127.0.0.1' || normalized === '::1' || normalized === '[::1]'
  }
  const resolveHost = (baseUrl: string) => {
    try {
      if (!baseUrl) return window.location.hostname
      return new URL(baseUrl, window.location.origin).hostname
    } catch {
      return window.location.hostname
    }
  }
  const apiBaseUrl = normalizeBase(import.meta.env.VITE_API_BASE_URL)
  const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const wsBaseUrl = normalizeBase(import.meta.env.VITE_WS_BASE_URL) || `${wsProtocol}://${window.location.host}/ws`
  const apiHost = resolveHost(apiBaseUrl)
  const isLocalClient = isLoopbackHost(window.location.hostname) && isLoopbackHost(apiHost)
  
  // --- UI State ---
  const tasks = ref<Task[]>([])
  const selectedTask = ref<Task | null>(null)
  const videoUrl = ref('')
  const selectedFile = ref<File | null>(null)
  const localFilePath = ref('')
  const quality = ref<VideoQuality>('audio_only')
  const summaryMode = ref<Exclude<SummaryMode, 'auto'>>('standard')
  const isSubmitting = ref(false)
  const error = ref<string | null>(null)
  const activeTab = ref<'summary' | 'transcript'>('summary')
  const isSidebarOpen = ref(false)
  const llmProviders = ref<LLMProvider[]>([])
  const llmSettings = ref<LLMSettings | null>(null)
  const isUpdatingLlmSettings = ref(false)
  const transcriptionSettings = ref<TranscriptionSettings | null>(null)
  const isUpdatingTranscriptionSettings = ref(false)
  const summarizationSettings = ref<SummarizationSettings | null>(null)
  const isUpdatingSummarizationSettings = ref(false)
  const isReadingBilibiliCookieFromBrowser = ref(false)

  let ws: WebSocket | null = null
  let submitAbortController: AbortController | null = null

  // --- Actions ---
  const fetchTasks = async () => {
    try {
      const response = await axios.get(`${apiBaseUrl}/tasks/`)
      tasks.value = response.data
      
      // Sync selected task details
      if (selectedTask.value) {
        const current = tasks.value.find(t => t.id === selectedTask.value?.id)
        if (current) {
          // Merge updates
          selectedTask.value = { ...selectedTask.value, ...current }
        }
      }
    } catch (err) {
      console.error('Failed to fetch tasks:', err)
      error.value = '获取任务列表失败'
    }
  }

  const submitTask = async () => {
    // localhost 场景优先使用本地路径直读（避免文件上传复制）
    if (isLocalClient && localFilePath.value.trim()) {
      await submitLocalPathTask(localFilePath.value)
      return
    }

    // 文件上传优先
    if (selectedFile.value) {
      await uploadFile(selectedFile.value)
      return
    }

    // URL 提交
    const resolvedUrl = extractFirstUrl(videoUrl.value)
    if (!resolvedUrl) {
      error.value = '请输入有效视频链接，或粘贴包含链接的文本。'
      return
    }

    const controller = new AbortController()
    submitAbortController = controller
    isSubmitting.value = true
    error.value = null
    try {
      const payload: CreateTaskRequest = {
        video_url: resolvedUrl,
        quality: quality.value,
        summary_mode: summaryMode.value,
      }
      await axios.post(`${apiBaseUrl}/tasks/`, payload, {
        signal: controller.signal
      })
      videoUrl.value = ''
      // No need to fetchTasks here, WS will notify
    } catch (err) {
      if (isCanceledRequest(err)) {
        return
      }
      console.error('Failed to submit task:', err)
      error.value = getAxiosErrorMessage(err, '提交任务失败')
    } finally {
      if (submitAbortController === controller) {
        submitAbortController = null
        isSubmitting.value = false
      }
    }
  }

  const submitLocalPathTask = async (filePath: string) => {
    const normalized = filePath.trim()
    if (!normalized) {
      error.value = '请输入本地文件路径'
      return
    }

    const controller = new AbortController()
    submitAbortController = controller
    isSubmitting.value = true
    error.value = null
    try {
      await axios.post(`${apiBaseUrl}/upload/local-path`, {
        file_path: normalized,
        summary_mode: summaryMode.value,
      }, {
        signal: controller.signal
      })
      localFilePath.value = ''
      selectedFile.value = null
    } catch (err) {
      if (isCanceledRequest(err)) {
        return
      }
      console.error('Failed to submit local path task:', err)
      error.value = getAxiosErrorMessage(err, '本地路径提交失败')
    } finally {
      if (submitAbortController === controller) {
        submitAbortController = null
        isSubmitting.value = false
      }
    }
  }

  const uploadFile = async (file: File) => {
    const controller = new AbortController()
    submitAbortController = controller
    isSubmitting.value = true
    error.value = null
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('summary_mode', summaryMode.value)

      await axios.post(`${apiBaseUrl}/upload`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data'
        },
        signal: controller.signal
      })

      selectedFile.value = null
      localFilePath.value = ''
      // No need to fetchTasks here, WS will notify
    } catch (err) {
      if (isCanceledRequest(err)) {
        return
      }
      console.error('Failed to upload file:', err)
      error.value = getAxiosErrorMessage(err, '上传失败')
    } finally {
      if (submitAbortController === controller) {
        submitAbortController = null
        isSubmitting.value = false
      }
    }
  }

  const cancelSubmitting = () => {
    if (submitAbortController) {
      submitAbortController.abort()
      submitAbortController = null
    }
    isSubmitting.value = false
  }

  const selectTask = async (task: Task) => {
    try {
      const response = await axios.get(`${apiBaseUrl}/tasks/${task.id}`)
      selectedTask.value = response.data
      if (selectedTask.value?.status === 'PENDING' || selectedTask.value?.status === 'DOWNLOADING' || selectedTask.value?.status === 'TRANSCRIBING' || selectedTask.value?.status === 'SUMMARIZING') {
        activeTab.value = 'summary'
      }
    } catch (err) {
      console.error('Failed to fetch task details:', err)
      error.value = '获取任务详情失败'
    }
  }

  const downloadContent = (type: 'summary' | 'transcript') => {
    if (!selectedTask.value) return
    
    const topic = selectedTask.value.topic || selectedTask.value.title || new Date().toLocaleString('zh-CN').replace(/[/:]/g, '-')
    let content = ''
    let filename = ''
    
    if (type === 'summary') {
      content = selectedTask.value.summary || ''
      filename = `AI总结-${topic}.md`
    } else {
      content = selectedTask.value.transcript || ''
      filename = `视频转录-${topic}.md`
    }
    
    const blob = new Blob([content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }

  const connectWebSocket = () => {
    ws = new WebSocket(wsBaseUrl)
    
    ws.onopen = () => {
      console.log('WebSocket connected')
      // Fetch latest state on reconnection to sync any missed updates
      fetchTasks()
      // Also refresh the selected task details if one is selected
      if (selectedTask.value) {
        selectTask(selectedTask.value).catch(err => {
          console.error('Failed to refresh selected task:', err)
        })
      }
    }
    
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.type === 'task_update') {
        const updatedTask = data.task
        const index = tasks.value.findIndex(t => t.id === updatedTask.id)
        if (index !== -1) {
          tasks.value[index] = updatedTask
        } else {
          tasks.value.unshift(updatedTask)
        }
        
        if (selectedTask.value?.id === updatedTask.id) {
          // Merge updates to preserve details that might not be in the broadcast
          selectedTask.value = { ...selectedTask.value, ...updatedTask }
        }
      } else if (data.type === 'progress_update') {
        const { task_id, progress } = data
        const task = tasks.value.find(t => t.id === task_id)
        if (task) {
          task.progress = progress
        }
        if (selectedTask.value && selectedTask.value.id === task_id) {
          selectedTask.value.progress = progress
        }
      }
    }

    ws.onclose = () => {
      console.log('WebSocket disconnected, retrying in 3s...')
      setTimeout(connectWebSocket, 3000)
    }

    ws.onerror = (err) => {
      console.error('WebSocket error:', err)
      ws?.close()
    }
  }

  const fetchLlmProviders = async () => {
    try {
      const response = await axios.get(`${apiBaseUrl}/llm/providers`)
      llmProviders.value = response.data
    } catch (err) {
      console.error('Failed to fetch LLM providers:', err)
      error.value = '获取 LLM 供应商列表失败'
    }
  }

  const fetchLlmSettings = async () => {
    try {
      const response = await axios.get(`${apiBaseUrl}/llm/settings`)
      llmSettings.value = response.data
    } catch (err) {
      console.error('Failed to fetch LLM settings:', err)
      error.value = '获取 LLM 配置失败'
    }
  }

  const updateLlmSettings = async (payload: UpdateLLMSettingsRequest) => {
    isUpdatingLlmSettings.value = true
    try {
      const response = await axios.put(`${apiBaseUrl}/llm/settings`, payload)
      llmSettings.value = response.data
      return response.data as LLMSettings
    } catch (err) {
      console.error('Failed to update LLM settings:', err)
      if (axios.isAxiosError(err) && err.response) {
        error.value = err.response.data?.detail || '更新 LLM 配置失败'
      } else {
        error.value = '更新 LLM 配置失败'
      }
      throw err
    } finally {
      isUpdatingLlmSettings.value = false
    }
  }

  const fetchTranscriptionSettings = async () => {
    try {
      const response = await axios.get(`${apiBaseUrl}/transcription/settings`)
      transcriptionSettings.value = response.data
    } catch (err) {
      console.error('Failed to fetch transcription settings:', err)
      error.value = '获取转录配置失败'
    }
  }

  const updateTranscriptionSettings = async (payload: UpdateTranscriptionSettingsRequest) => {
    isUpdatingTranscriptionSettings.value = true
    try {
      const response = await axios.put(`${apiBaseUrl}/transcription/settings`, payload)
      transcriptionSettings.value = response.data
      return response.data as TranscriptionSettings
    } catch (err) {
      console.error('Failed to update transcription settings:', err)
      if (axios.isAxiosError(err) && err.response) {
        error.value = err.response.data?.detail || '更新转录配置失败'
      } else {
        error.value = '更新转录配置失败'
      }
      throw err
    } finally {
      isUpdatingTranscriptionSettings.value = false
    }
  }

  const testLlm = async () => {
    try {
      const response = await axios.post(`${apiBaseUrl}/llm/test`)
      return response.data
    } catch (err) {
      console.error('Failed to test LLM:', err)
      if (axios.isAxiosError(err) && err.response) {
        error.value = err.response.data?.detail || '测试 LLM 失败'
      } else {
        error.value = '测试 LLM 失败'
      }
      throw err
    }
  }

  const fetchSummarizationSettings = async () => {
    try {
      const response = await axios.get(`${apiBaseUrl}/summarization/settings`)
      summarizationSettings.value = response.data
    } catch (err) {
      console.error('Failed to fetch summarization settings:', err)
      error.value = '获取总结配置失败'
    }
  }

  const updateSummarizationSettings = async (payload: UpdateSummarizationSettingsRequest) => {
    isUpdatingSummarizationSettings.value = true
    try {
      const response = await axios.put(`${apiBaseUrl}/summarization/settings`, payload)
      summarizationSettings.value = response.data
      return response.data as SummarizationSettings
    } catch (err) {
      console.error('Failed to update summarization settings:', err)
      if (axios.isAxiosError(err) && err.response) {
        error.value = err.response.data?.detail || '更新总结配置失败'
      } else {
        error.value = '更新总结配置失败'
      }
      throw err
    } finally {
      isUpdatingSummarizationSettings.value = false
    }
  }

  const readBilibiliCookieFromBrowser = async (): Promise<BilibiliCookieFromBrowserResult> => {
    isReadingBilibiliCookieFromBrowser.value = true
    try {
      const response = await axios.post(`${apiBaseUrl}/transcription/settings/bilibili-cookie/from-browser`)
      const result = response.data as BilibiliCookieFromBrowserResult
      if (result.success) {
        // Refresh transcription settings to reflect the new cookie
        await fetchTranscriptionSettings()
      }
      return result
    } catch (err) {
      console.error('Failed to read Bilibili cookie from browser:', err)
      if (axios.isAxiosError(err) && err.response) {
        error.value = err.response.data?.detail || '从浏览器读取 Cookie 失败'
      } else {
        error.value = '从浏览器读取 Cookie 失败'
      }
      throw err
    } finally {
      isReadingBilibiliCookieFromBrowser.value = false
    }
  }

  const checkBilibiliVideoInfo = async (url: string): Promise<BilibiliVideoInfo | null> => {
    try {
      const response = await axios.post(`${apiBaseUrl}/bilibili/video-info`, { url })
      return response.data as BilibiliVideoInfo
    } catch (err) {
      console.error('Failed to check Bilibili video info:', err)
      return null
    }
  }

  const submitTaskWithParts = async (
    videoUrl: string,
    partsConfig: BilibiliPartsConfig,
    abortSignal?: AbortSignal
  ): Promise<void> => {
    const controller = new AbortController()
    submitAbortController = controller
    isSubmitting.value = true
    error.value = null

    try {
      const payload = {
        video_url: videoUrl,
        quality: quality.value,
        summary_mode: summaryMode.value,
        bilibili_parts: partsConfig,
      }
      await axios.post(`${apiBaseUrl}/tasks/`, payload, {
        signal: abortSignal || controller.signal
      })
    } catch (err) {
      if (isCanceledRequest(err)) {
        return
      }
      console.error('Failed to submit task with parts:', err)
      error.value = getAxiosErrorMessage(err, '提交任务失败')
      throw err
    } finally {
      if (submitAbortController === controller) {
        submitAbortController = null
        isSubmitting.value = false
      }
    }
  }

  // --- Lifecycle ---
  onMounted(() => {
    fetchTasks()
    fetchLlmProviders()
    fetchLlmSettings()
    fetchTranscriptionSettings()
    fetchSummarizationSettings()
    connectWebSocket()
  })

  onUnmounted(() => {
    if (ws) {
      ws.close()
    }
  })

  return {
    // State
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
    isSidebarOpen,
    llmProviders,
    llmSettings,
    isUpdatingLlmSettings,
    transcriptionSettings,
    isUpdatingTranscriptionSettings,
    summarizationSettings,
    isUpdatingSummarizationSettings,
    isReadingBilibiliCookieFromBrowser,

    // Actions
    submitTask,
    submitLocalPathTask,
    uploadFile,
    cancelSubmitting,
    selectTask,
    fetchTasks,
    fetchLlmProviders,
    fetchLlmSettings,
    updateLlmSettings,
    fetchTranscriptionSettings,
    updateTranscriptionSettings,
    fetchSummarizationSettings,
    updateSummarizationSettings,
    testLlm,
    readBilibiliCookieFromBrowser,
    checkBilibiliVideoInfo,
    submitTaskWithParts,
    isBilibiliUrl,
    downloadContent,
    copyContent: async (type: 'summary' | 'transcript') => {
      if (!selectedTask.value) return false

      // 直接使用当前 selectedTask 的数据，与 compiledMarkdown 保持一致
      let text = ''
      if (type === 'summary') {
        text = selectedTask.value.summary || ''
      } else {
        text = selectedTask.value.transcript || ''
      }

      if (!text) return false

      try {
        // 优先使用现代 Clipboard API（需要安全上下文：HTTPS 或 localhost）
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(text)
          return true
        }

        // 降级到传统方法（兼容非安全上下文，如局域网 HTTP）
        return fallbackCopyToClipboard(text)
      } catch (err) {
        console.error('Failed to copy text:', err)
        // 如果现代 API 失败，尝试降级方法
        try {
          return fallbackCopyToClipboard(text)
        } catch (fallbackErr) {
          console.error('Fallback copy also failed:', fallbackErr)
          return false
        }
      }
    },
    deleteTask: async (taskId: string) => {
      if (!confirm('确定要删除这个任务吗？此操作不可恢复。')) {
        return false
      }
      try {
        await axios.delete(`${apiBaseUrl}/tasks/${taskId}`)
        tasks.value = tasks.value.filter(t => t.id !== taskId)
        if (selectedTask.value?.id === taskId) {
          selectedTask.value = null
        }
        return true
      } catch (err) {
        console.error('Failed to delete task:', err)
        error.value = '删除任务失败'
        return false
      }
    },
    reSummarize: async (taskId: string) => {
      try {
        await axios.post(`${apiBaseUrl}/tasks/${taskId}/re-summarize`, {
          summary_mode: summaryMode.value
        })
        // No need to do more, WS will update the status
      } catch (err) {
        console.error('Failed to re-summarize task:', err)
        error.value = '重新总结失败'
      }
    },
    reTranscribe: async (taskId: string) => {
      try {
        await axios.post(`${apiBaseUrl}/tasks/${taskId}/re-transcribe`, {
          summary_mode: summaryMode.value
        })
        // No need to do more, WS will update the status
      } catch (err) {
        console.error('Failed to re-transcribe task:', err)
        if (axios.isAxiosError(err) && err.response) {
          error.value = err.response.data?.detail || '重新转录失败'
        } else {
          error.value = '重新转录失败'
        }
      }
    },
    updateTaskTopic: async (taskId: string, newTopic: string) => {
      try {
        await axios.patch(`${apiBaseUrl}/tasks/${taskId}`, { topic: newTopic })
        // WS will update the task list and selected task
      } catch (err) {
        console.error('Failed to update task topic:', err)
        error.value = '更新主题失败'
        throw err
      }
    }
  }
}
