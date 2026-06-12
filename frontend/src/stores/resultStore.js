import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '../api/axios'

// Privacy label categories with Chinese names, colors, and icons
export const LABEL_MAP = {
  private_person: { zh: '姓名', color: '#FCA5A5', icon: 'user' },           // red-300
  private_phone: { zh: '手机号码', color: '#93C5FD', icon: 'phone' },       // blue-300
  private_email: { zh: '电子邮箱', color: '#86EFAC', icon: 'mail' },        // green-300
  account_number: { zh: '账号/证件号', color: '#FDE68A', icon: 'id' },      // amber-200
  private_address: { zh: '地址', color: '#C4B5FD', icon: 'location' },      // violet-300
  private_date: { zh: '日期', color: '#FBD38D', icon: 'calendar' },         // orange-300
  secret: { zh: '密码/密钥', color: '#F9A8D4', icon: 'lock' },              // pink-300
  private_url: { zh: 'URL', color: '#A5F3FC', icon: 'link' },               // cyan-200
  private_bankcard: { zh: '银行卡号', color: '#D4A5FF', icon: 'id' },       // purple-300
  private_idcard: { zh: '身份证号', color: '#FFB3B3', icon: 'id' },         // light-red
  organization: { zh: '机构名称', color: '#B5D8CC', icon: 'location' },     // teal-300
  other_person: { zh: '其他人名', color: '#FFD6A5', icon: 'user' },         // peach
}

export const ICON_PATHS = {
  user: 'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z',
  phone: 'M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z',
  mail: 'M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z',
  id: 'M10 6H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V8a2 2 0 00-2-2h-5m-4 0V5a2 2 0 114 0v1m-4 0a2 2 0 104 0m-5 8a2 2 0 100-4 2 2 0 000 4zm0 0v1.5a2.5 2.5 0 005 0V14',
  location: 'M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z M15 11a3 3 0 11-6 0 3 3 0 016 0z',
  calendar: 'M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z',
  lock: 'M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z',
  link: 'M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1',
}

/**
 * Get the background color for a label, with fallback.
 * @param {string} label
 * @returns {string} CSS color string
 */
export function getLabelColor(label) {
  return LABEL_MAP[label]?.color || '#E5E7EB'
}

/**
 * Get Chinese display name for a label.
 * @param {string} label
 * @returns {string}
 */
export function getLabelZh(label) {
  return LABEL_MAP[label]?.zh || label
}

export const useResultStore = defineStore('result', () => {
  const taskId = ref(null)
  const loading = ref(false)
  const error = ref(null)
  const fileInfo = ref(null)
  const blocks = ref([])
  const summary = ref(null)

  /**
   * Fetch detection results for a given task.
   * @param {string} id - task_id
   */
  async function fetchResult(id) {
    loading.value = true
    error.value = null
    taskId.value = id
    fileInfo.value = null
    blocks.value = []
    summary.value = null

    try {
      const response = await api.get(`/result/${id}`)
      const data = response.data

      if (data.status === 'processing') {
        error.value = '任务仍在处理中，请稍后再试'
        return
      }

      // Support two API formats:
      // Format A (local main.py): { file_info, blocks[], summary }
      // Format B (container app.py): { filename, details[], by_type, total_pii }
      if (data.blocks && data.summary) {
        // Format A
        fileInfo.value = data.file_info || null
        blocks.value = data.blocks || []
        summary.value = data.summary || null
      } else if (data.details) {
        // Format B — transform to internal format
        const details = data.details || []
        const byType = data.by_type || {}

        fileInfo.value = {
          filename: data.filename || 'unknown',
          size_bytes: null,
          block_count: data.text_segments ?? details.length,
          char_count: data.char_count ?? 0,
          line_count: data.line_count ?? 0,
          extension: data.filename?.includes('.') ? '.' + data.filename.split('.').pop() : '',
        }

        blocks.value = details.map((d, idx) => {
          const spans = (d.spans || []).map(s => ({
            label: s.label,
            start: s.start,
            end: s.end,
            text: s.text,
            placeholder: s.placeholder || `[${LABEL_MAP[s.label]?.zh || s.label}]`,
          }))
          return {
            block_index: idx,
            original_text: d.original || '',
            redacted_text: d.redacted || '',
            detected_spans: spans,
            metadata: { section: d.section },
          }
        })

        const totalSpans = Object.values(byType).reduce((a, b) => a + b, 0)
        summary.value = {
          total_spans: data.total_pii || totalSpans,
          label_counts: byType,
        }

        // Distinguish "no text extracted" from "text found but no PII"
        // Only trigger error when text_segments is explicitly 0 (not null/undefined from old cache)
        if (data.text_segments !== undefined && data.text_segments !== null && data.text_segments === 0) {
          error.value = '文件未提取到可检测的文本内容。该文件可能已是脱敏文件、扫描件无法解析，或文件内容为空。'
        }
      } else {
        error.value = '未知的结果格式'
      }
    } catch (err) {
      error.value = err.response?.data?.detail || '加载结果失败'
    } finally {
      loading.value = false
    }
  }

  /**
   * Clear result state (when navigating away).
   */
  function clearResult() {
    taskId.value = null
    fileInfo.value = null
    blocks.value = []
    summary.value = null
    error.value = null
    loading.value = false
  }

  return {
    taskId,
    loading,
    error,
    fileInfo,
    blocks,
    summary,
    fetchResult,
    clearResult,
  }
})
