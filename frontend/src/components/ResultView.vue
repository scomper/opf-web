<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useResultStore, LABEL_MAP, ICON_PATHS, getLabelColor, getLabelZh } from '../stores/resultStore'
import { useTaskStore } from '../stores/taskStore'
import { useToastStore } from '../stores/toastStore'
import api from '../api/axios'

const props = defineProps({
  taskId: { type: String, required: true },
})

const emit = defineEmits(['back', 'switchTask'])

const resultStore = useResultStore()
const taskStore = useTaskStore()
const toastStore = useToastStore()

// Other completed tasks with PII for quick navigation
const otherTasks = computed(() =>
  taskStore.tasks.filter(t => t.status === 'completed' && t.task_id !== props.taskId && (t.total_pii || 0) > 0)
)

// Tooltip state
const tooltipVisible = ref(false)
const tooltipLabel = ref('')
const tooltipText = ref('')
const tooltipSpanKey = ref('') // blockIndex:start:end to identify the span
const tooltipX = ref(0)
const tooltipY = ref(0)

// ─── Dismissed spans (persistent) ──────────────────────────────
// Key per task: "opf_dismissed_{taskId}" → Set of span keys
// Learning log: "opf_dismiss_log" → [{text, label, timestamp, taskId}]
const DISMISSED_PREFIX = 'opf_dismissed_'
const DISMISS_LOG_KEY = 'opf_dismiss_log'

function loadDismissed(taskId) {
  try {
    const raw = localStorage.getItem(DISMISSED_PREFIX + taskId)
    return raw ? new Set(JSON.parse(raw)) : new Set()
  } catch { return new Set() }
}

function saveDismissed(taskId, set) {
  localStorage.setItem(DISMISSED_PREFIX + taskId, JSON.stringify([...set]))
}

function appendDismissLog(entry) {
  try {
    const log = JSON.parse(localStorage.getItem(DISMISS_LOG_KEY) || '[]')
    log.push(entry)
    // Keep last 500 entries
    if (log.length > 500) log.splice(0, log.length - 500)
    localStorage.setItem(DISMISS_LOG_KEY, JSON.stringify(log))
  } catch { /* ignore */ }
}

const dismissedSpans = ref(new Set())

// Watch taskId changes (e.g. from "other tasks" navigation)
watch(() => props.taskId, (newId) => {
  if (newId) {
    selectedLabel.value = null
    dismissedSpans.value = loadDismissed(newId)
    resultStore.fetchResult(newId)
  }
})

onMounted(() => {
  dismissedSpans.value = loadDismissed(props.taskId)
  resultStore.fetchResult(props.taskId)
  taskStore.fetchTasks()
  // Close tooltip on outside click
  document.addEventListener('click', onDocumentClick)
})

onUnmounted(() => {
  resultStore.clearResult()
  document.removeEventListener('click', onDocumentClick)
})

// ─── Computed ────────────────────────────────────────────────────

// Build a map of dismissed counts per label from dismissedSpans set
const dismissedCounts = computed(() => {
  const counts = {}
  for (const key of dismissedSpans.value) {
    // key format: "blockIndex:label:text"
    const parts = key.split(':')
    if (parts.length >= 2) {
      const label = parts[1]
      counts[label] = (counts[label] || 0) + 1
    }
  }
  return counts
})

const totalSpans = computed(() => {
  const raw = resultStore.summary?.total_spans ?? 0
  const dismissed = Object.values(dismissedCounts.value).reduce((a, b) => a + b, 0)
  return Math.max(0, raw - dismissed)
})

const labelCounts = computed(() => {
  const counts = resultStore.summary?.label_counts ?? {}
  const full = {}
  for (const key of Object.keys(LABEL_MAP)) {
    full[key] = Math.max(0, (counts[key] || 0) - (dismissedCounts.value[key] || 0))
  }
  return full
})

const maxLabelCount = computed(() => {
  return Math.max(1, ...Object.values(labelCounts.value))
})

// File stats for "clean report" — prefer backend fileInfo, fallback to blocks
const fileStats = computed(() => {
  const fi = resultStore.fileInfo || {}
  const blocks = resultStore.blocks || []
  const allText = blocks.map(b => b.original_text || '').join('\n')
  const charCount = fi.char_count || allText.length || 0
  const lineCount = fi.line_count || (allText ? allText.split('\n').length : 0)
  const ext = fi.extension || fi.filename?.split('.').pop() || ''
  const blockCount = fi.block_count || blocks.length || 0
  return { charCount, lineCount, ext, blockCount }
})

// Filter state
const selectedLabel = ref(null)

function toggleLabelFilter(label) {
  selectedLabel.value = selectedLabel.value === label ? null : label
}

// Sorted labels by count descending (for statistics display)
const sortedLabels = computed(() => {
  return Object.entries(LABEL_MAP)
    .map(([key, entry]) => ({ key, entry, count: labelCounts.value[key] || 0 }))
    .sort((a, b) => b.count - a.count)
})

// Is this a PDF? (can't redact in-place, show report instead)
const isPdf = computed(() => {
  const name = resultStore.fileInfo?.filename || ''
  return name.toLowerCase().endsWith('.pdf')
})

// Filtered blocks: if a label is selected, only show blocks that have spans with that label
const filteredBlocks = computed(() => {
  if (!selectedLabel.value) return resultStore.blocks
  return resultStore.blocks.filter(block =>
    block.detected_spans?.some(span => span.label === selectedLabel.value)
  )
})

// ─── Segment builder ─────────────────────────────────────────────
// Convert a block's original_text + detected_spans into displayable segments

function buildSegments(block) {
  const text = block.original_text || ''
  const spans = (block.detected_spans || []).filter(
    s => !dismissedSpans.value.has(`${block.block_index}:${s.label}:${s.text}`)
  )
  if (spans.length === 0) {
    return [{ type: 'plain', text }]
  }

  // Sort spans by start position
  const sorted = [...spans].sort((a, b) => a.start - b.start)
  const segments = []
  let cursor = 0

  for (const span of sorted) {
    if (span.start > cursor) {
      segments.push({ type: 'plain', text: text.slice(cursor, span.start) })
    }
    segments.push({
      type: 'span',
      text: span.text,
      label: span.label,
      placeholder: span.placeholder,
    })
    cursor = span.end
  }
  if (cursor < text.length) {
    segments.push({ type: 'plain', text: text.slice(cursor) })
  }

  return segments
}

// ─── Tooltip ─────────────────────────────────────────────────────

function onSpanClick(event, segment, blockIndex) {
  event.stopPropagation()
  tooltipLabel.value = segment.label
  tooltipText.value = segment.text
  tooltipSpanKey.value = `${blockIndex}:${segment.label}:${segment.text}`

  // Position tooltip near the click
  const rect = event.target.getBoundingClientRect()
  tooltipX.value = rect.left + rect.width / 2
  tooltipY.value = rect.top - 8
  tooltipVisible.value = true
}

function onDocumentClick() {
  tooltipVisible.value = false
}

function dismissSpan() {
  const key = tooltipSpanKey.value
  dismissedSpans.value.add(key)
  saveDismissed(props.taskId, dismissedSpans.value)
  appendDismissLog({
    text: tooltipText.value,
    label: tooltipLabel.value,
    action: 'dismiss',
    taskId: props.taskId,
    timestamp: new Date().toISOString(),
  })
  tooltipVisible.value = false
  toastStore.success('已移除该标记，后续同类检测将参考此操作')
}

async function addSpanToWhitelist() {
  const text = tooltipText.value
  const label = tooltipLabel.value
  try {
    // Fetch current whitelist, append new pattern, save
    const resp = await api.get('/whitelist')
    const rules = resp.data.rules || []
    // Escape special regex chars to make it a literal match
    const escaped = text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    if (!rules.some(r => r.pattern === escaped)) {
      rules.push({ pattern: escaped, reason: `从结果页添加: ${getLabelZh(label)}` })
      await api.post('/whitelist', { rules })
    }
    const key = tooltipSpanKey.value
    dismissedSpans.value.add(key)
    saveDismissed(props.taskId, dismissedSpans.value)
    appendDismissLog({
      text,
      label,
      action: 'whitelist',
      taskId: props.taskId,
      timestamp: new Date().toISOString(),
    })
    tooltipVisible.value = false
    toastStore.success(`"${text}" 已加入白名单，重新检测时将跳过`)
  } catch {
    toastStore.error('加入白名单失败')
  }
}

// ─── Download ────────────────────────────────────────────────────

async function downloadRedacted() {
  try {
    const response = await api.get(`/download/${props.taskId}`, {
      responseType: 'blob',
    })

    // Extract filename from Content-Disposition header or build one
    let filename = 'redacted_file'
    const disposition = response.headers['content-disposition']
    if (disposition) {
      const match = disposition.match(/filename\*?=(?:UTF-8'')?["']?([^"';\n]+)/i)
      if (match) {
        filename = decodeURIComponent(match[1])
      }
    }

    // Trigger browser download
    const url = URL.createObjectURL(response.data)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)

    toastStore.success('文件下载成功')
  } catch (err) {
    // blob error responses need special handling
    if (err.response?.data instanceof Blob) {
      try {
        const text = await err.response.data.text()
        const json = JSON.parse(text)
        toastStore.error(json.detail || '文件下载失败')
      } catch {
        toastStore.error('文件下载失败')
      }
    } else {
      toastStore.error(err.response?.data?.detail || '文件下载失败')
    }
  }
}

// ─── Helpers ─────────────────────────────────────────────────────

function formatFileSize(bytes) {
  if (!bytes) return '—'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}
</script>

<template>
  <div class="w-full">
    <!-- Header bar -->
    <div class="flex items-center justify-between mb-6">
      <div class="flex items-center gap-3">
        <button
          class="flex items-center gap-1.5 text-sm text-gray-600 hover:text-blue-600 transition-colors"
          @click="emit('back')"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
          </svg>
          返回任务列表
        </button>
      </div>

      <button
        v-if="resultStore.blocks.length > 0"
        class="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors shadow-sm"
        @click="downloadRedacted"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        {{ isPdf ? '导出检测报告' : '下载脱敏文件' }}
      </button>
    </div>

    <!-- Loading state -->
    <div v-if="resultStore.loading" class="text-center py-20">
      <svg class="animate-spin h-8 w-8 mx-auto text-blue-500 mb-4" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
      <p class="text-gray-500">正在加载检测结果…</p>
    </div>

    <!-- Error state -->
    <div v-else-if="resultStore.error" class="text-center py-20">
      <div class="text-yellow-500 text-4xl mb-4">⚠</div>
      <p class="text-gray-700 font-medium mb-2">{{ resultStore.error }}</p>
      <button
        class="px-4 py-2 bg-gray-100 text-gray-700 text-sm rounded-lg hover:bg-gray-200 transition-colors"
        @click="resultStore.fetchResult(props.taskId)"
      >
        重试
      </button>
    </div>

    <!-- Result content (or clean report) -->
    <template v-else>
      <!-- Has PII — show full result view -->
      <div v-if="resultStore.blocks.length > 0" class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <!-- Left: document content (2/3) -->
        <div class="lg:col-span-2 space-y-6">
          <!-- File info card -->
          <div v-if="resultStore.fileInfo" class="bg-white rounded-xl border p-4">
            <h3 class="text-sm font-semibold text-gray-600 mb-2">文档内容</h3>
            <div class="flex flex-wrap gap-4 text-xs text-gray-500">
              <span>文件名：{{ resultStore.fileInfo.filename }}</span>
              <span>大小：{{ formatFileSize(resultStore.fileInfo.size_bytes) }}</span>
              <span>文本块：{{ resultStore.fileInfo.block_count }} 个</span>
            </div>
          </div>

          <!-- Filter indicator -->
          <div
            v-if="selectedLabel"
            class="flex items-center gap-2 px-4 py-2 bg-blue-50 border border-blue-200 rounded-lg text-sm"
          >
            <div
              class="w-4 h-4 rounded flex items-center justify-center flex-shrink-0"
              :style="{ backgroundColor: getLabelColor(selectedLabel) + '30' }"
            >
              <svg class="w-2.5 h-2.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"
                :style="{ color: getLabelColor(selectedLabel) }"
              >
                <path stroke-linecap="round" stroke-linejoin="round" :d="ICON_PATHS[LABEL_MAP[selectedLabel]?.icon]" />
              </svg>
            </div>
            <span class="text-blue-700">
              正在筛选：<span class="font-semibold">{{ getLabelZh(selectedLabel) }}</span>
            </span>
            <span class="text-blue-500 text-xs">
              （{{ filteredBlocks.length }} / {{ resultStore.blocks.length }} 个文本块）
            </span>
            <button
              class="ml-auto text-blue-600 hover:text-blue-800 text-xs font-medium"
              @click="selectedLabel = null"
            >
              清除筛选
            </button>
          </div>

          <!-- Text blocks with highlights -->
          <div
            v-for="block in filteredBlocks"
            :key="block.block_index"
            class="bg-white rounded-xl border p-5"
          >
            <div class="flex items-center gap-2 mb-3">
              <span class="text-xs font-mono text-gray-400">文本块 #{{ block.block_index + 1 }}</span>
              <span
                v-if="block.detected_spans?.length"
                class="text-xs bg-red-50 text-red-600 px-2 py-0.5 rounded-full"
              >
                {{ block.detected_spans.length }} 项检测
              </span>
            </div>
            <div class="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap break-words">
              <template v-for="(seg, i) in buildSegments(block)" :key="i">
                <span v-if="seg.type === 'plain'">{{ seg.text }}</span>
                <span
                  v-else
                  class="cursor-pointer rounded px-0.5 border-b-2 border-dashed transition-all hover:brightness-90"
                  :class="{
                    'opacity-30': selectedLabel && selectedLabel !== seg.label,
                  }"
                  :style="{
                    backgroundColor: getLabelColor(seg.label),
                    borderColor: getLabelColor(seg.label),
                  }"
                  @click="onSpanClick($event, seg, block.block_index)"
                >{{ seg.text }}</span>
              </template>
            </div>
          </div>
        </div>

        <!-- Right sidebar (1/3): Statistics + Legend -->
        <div class="space-y-6">
          <!-- Statistics panel -->
          <div class="bg-white rounded-xl border p-5">
            <h3 class="text-base font-semibold text-gray-800 mb-4">检测统计</h3>

            <!-- Total count -->
            <div class="text-center mb-5">
              <div class="text-3xl font-bold text-gray-900">{{ totalSpans }}</div>
              <div class="text-sm text-gray-500 mt-1">检测总数</div>
            </div>

            <!-- Bar breakdown by category (clickable to filter, sorted by count desc) -->
            <div class="space-y-3">
              <div
                v-for="item in sortedLabels"
                :key="item.key"
                class="flex items-center gap-3 cursor-pointer rounded-lg px-2 py-1 -mx-2 transition-all"
                :class="{
                  'opacity-40': selectedLabel && selectedLabel !== item.key,
                  'hover:opacity-100': selectedLabel && selectedLabel !== item.key,
                }"
                @click="toggleLabelFilter(item.key)"
              >
                <!-- Icon -->
                <div
                  class="w-6 h-6 rounded-md flex items-center justify-center flex-shrink-0 transition-all"
                  :style="{
                    backgroundColor: selectedLabel === item.key ? item.entry.color + '30' : (selectedLabel ? '#F3F4F630' : item.entry.color + '20'),
                  }"
                >
                  <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"
                    :style="{ color: selectedLabel === item.key ? item.entry.color : (selectedLabel ? '#9CA3AF' : item.entry.color) }"
                  >
                    <path stroke-linecap="round" stroke-linejoin="round" :d="ICON_PATHS[item.entry.icon]" />
                  </svg>
                </div>
                <!-- Label name + count -->
                <span
                  class="text-xs w-24 flex-shrink-0 transition-colors"
                  :class="selectedLabel === item.key ? 'font-semibold text-gray-900' : 'text-gray-600'"
                >{{ item.entry.zh }}：<span class="font-mono">{{ item.count }}</span></span>
                <!-- Bar -->
                <div class="flex-1 bg-gray-100 rounded-full h-2 overflow-hidden">
                  <div
                    class="h-full rounded-full transition-all duration-500"
                    :style="{
                      width: (item.count / maxLabelCount) * 100 + '%',
                      backgroundColor: selectedLabel === item.key ? item.entry.color : (selectedLabel ? '#D1D5DB' : item.entry.color),
                    }"
                  />
                </div>
              </div>
            </div>
          </div>

          <!-- Quick task navigation -->
          <div v-if="otherTasks.length > 0" class="bg-white rounded-xl border p-5">
            <h3 class="text-sm font-semibold text-gray-800 mb-3">其他任务</h3>
            <div class="space-y-1.5 max-h-48 overflow-y-auto">
              <button
                v-for="t in otherTasks"
                :key="t.task_id"
                class="w-full flex items-center gap-2 px-2.5 py-1.5 text-left rounded-lg hover:bg-blue-50 transition-colors group"
                @click="emit('switchTask', t.task_id)"
              >
                <svg class="w-3.5 h-3.5 text-gray-300 group-hover:text-blue-500 flex-shrink-0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                <span class="text-xs text-gray-600 truncate group-hover:text-blue-700">{{ t.filename }}</span>
              </button>
            </div>
          </div>

        </div>
      </div>

      <!-- Clean report — no PII detected -->
      <div v-if="totalSpans === 0 && !resultStore.error" class="bg-white rounded-xl border p-8 mt-6 text-center">
        <div class="inline-flex items-center justify-center w-16 h-16 rounded-full bg-green-100 mb-4">
          <svg class="w-8 h-8 text-green-600" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
          </svg>
        </div>
        <h3 class="text-lg font-semibold text-gray-800 mb-1">文档安全</h3>
        <p class="text-sm text-green-600 mb-6">未检测到隐私信息</p>

        <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 max-w-md mx-auto">
          <div class="bg-gray-50 rounded-lg px-3 py-3">
            <div class="text-lg font-bold text-gray-800">{{ fileStats.ext || '—' }}</div>
            <div class="text-xs text-gray-500">文件类型</div>
          </div>
          <div class="bg-gray-50 rounded-lg px-3 py-3">
            <div class="text-lg font-bold text-gray-800">{{ fileStats.blockCount }}</div>
            <div class="text-xs text-gray-500">文本段</div>
          </div>
          <div class="bg-gray-50 rounded-lg px-3 py-3">
            <div class="text-lg font-bold text-gray-800">{{ fileStats.lineCount }}</div>
            <div class="text-xs text-gray-500">行数</div>
          </div>
          <div class="bg-gray-50 rounded-lg px-3 py-3">
            <div class="text-lg font-bold text-gray-800">{{ fileStats.charCount > 9999 ? (fileStats.charCount / 10000).toFixed(1) + '万' : fileStats.charCount }}</div>
            <div class="text-xs text-gray-500">字符数</div>
          </div>
        </div>
      </div>
    </template>

    <!-- Tooltip (teleported to body for correct stacking) -->
    <Teleport to="body">
      <div
        v-if="tooltipVisible"
        class="fixed z-[9999]"
        :style="{
          left: tooltipX + 'px',
          top: tooltipY + 'px',
          transform: 'translate(-50%, -100%)',
        }"
      >
        <div class="bg-gray-900 text-white text-xs rounded-lg shadow-xl px-3 py-2.5 max-w-xs mb-1">
          <!-- Label + text -->
          <div class="font-semibold mb-1">
            <span
              class="inline-block w-2.5 h-2.5 rounded-sm mr-1.5 align-middle"
              :style="{ backgroundColor: getLabelColor(tooltipLabel) }"
            />
            {{ getLabelZh(tooltipLabel) }}
          </div>
          <div class="text-gray-300 mb-2.5">
            <span class="text-gray-400">原文：</span>{{ tooltipText }}
          </div>
          <!-- Action buttons -->
          <div class="flex gap-2 border-t border-gray-700 pt-2">
            <button
              class="flex items-center gap-1 px-2 py-1 rounded bg-gray-700 hover:bg-gray-600 text-gray-200 hover:text-white transition-colors"
              @click.stop="dismissSpan"
            >
              <svg class="w-3 h-3" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
              移除
            </button>
            <button
              class="flex items-center gap-1 px-2 py-1 rounded bg-blue-800 hover:bg-blue-700 text-blue-200 hover:text-white transition-colors"
              @click.stop="addSpanToWhitelist"
            >
              <svg class="w-3 h-3" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
              </svg>
              加白名单
            </button>
          </div>
        </div>
        <!-- Arrow -->
        <div class="w-2.5 h-2.5 bg-gray-900 mx-auto transform rotate-45 -mt-1.5" />
      </div>
    </Teleport>
  </div>
</template>
