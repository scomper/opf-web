<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from "vue"
import { useTaskStore } from "../stores/taskStore"
import { useToastStore } from "../stores/toastStore"
import api from "../api/axios"

const emit = defineEmits(["viewResult"])

const taskStore = useTaskStore()
const toastStore = useToastStore()

// --- Constants ---
const LOCKED_KEY = "opf_locked_tasks"
const CLEAN_KEY = "opf_auto_clean_days"
const PAGE_SIZE = 10

// --- Lock state ---
const lockedIds = ref(new Set(JSON.parse(localStorage.getItem(LOCKED_KEY) || "[]")))

function persistLocked() {
  localStorage.setItem(LOCKED_KEY, JSON.stringify([...lockedIds.value]))
}

function toggleLock(taskId) {
  const s = new Set(lockedIds.value)
  if (s.has(taskId)) s.delete(taskId)
  else s.add(taskId)
  lockedIds.value = s
  persistLocked()
}

function isLocked(taskId) {
  return lockedIds.value.has(taskId)
}

// --- Auto-clean setting ---
const autoCleanDays = ref(parseInt(localStorage.getItem(CLEAN_KEY) || "0", 10))
const showCleanSetting = ref(false)

watch(autoCleanDays, (val) => {
  localStorage.setItem(CLEAN_KEY, String(val))
})

function getTimestamp(task) {
  if (!task.created_at) return 0
  if (typeof task.created_at === "number") return task.created_at * 1000
  const s = task.created_at
  return new Date(s.endsWith("Z") || s.includes("+") ? s : s + "Z").getTime()
}

const displayTasks = computed(() => {
  let tasks = taskStore.tasks
  if (autoCleanDays.value > 0) {
    const cutoff = Date.now() - autoCleanDays.value * 86400000
    tasks = tasks.filter((t) => getTimestamp(t) > cutoff)
  }
  return tasks
})

// --- Selection ---
const selectedIds = ref(new Set())

// Remove stale selected ids when displayTasks changes
watch(displayTasks, (tasks) => {
  const ids = new Set(tasks.map((t) => t.task_id))
  let changed = false
  const cleaned = new Set()
  for (const id of selectedIds.value) {
    if (ids.has(id)) cleaned.add(id)
    else changed = true
  }
  if (changed) selectedIds.value = cleaned
})

// --- Pagination ---
const currentPage = ref(1)

const totalPages = computed(() =>
  Math.max(1, Math.ceil(displayTasks.value.length / PAGE_SIZE))
)

const pagedTasks = computed(() => {
  const start = (currentPage.value - 1) * PAGE_SIZE
  return displayTasks.value.slice(start, start + PAGE_SIZE)
})

// Clamp page when displayTasks shrinks
watch(totalPages, (tp) => {
  if (currentPage.value > tp) currentPage.value = tp
})

function prevPage() {
  if (currentPage.value > 1) currentPage.value--
}

function nextPage() {
  if (currentPage.value < totalPages.value) currentPage.value++
}

// --- Selection (continued) ---
const allPageSelected = computed(() =>
  pagedTasks.value.length > 0 &&
  pagedTasks.value.every((t) => selectedIds.value.has(t.task_id))
)

const somePageSelected = computed(() =>
  !allPageSelected.value && pagedTasks.value.some((t) => selectedIds.value.has(t.task_id))
)

function toggleSelect(taskId) {
  const s = new Set(selectedIds.value)
  if (s.has(taskId)) s.delete(taskId)
  else s.add(taskId)
  selectedIds.value = s
}

function toggleSelectAllPage() {
  const s = new Set(selectedIds.value)
  if (allPageSelected.value) {
    for (const t of pagedTasks.value) s.delete(t.task_id)
  } else {
    for (const t of pagedTasks.value) s.add(t.task_id)
  }
  selectedIds.value = s
}

function selectAllAcrossPages() {
  selectedIds.value = new Set(displayTasks.value.map((t) => t.task_id))
}

// --- Rescan ---
async function rescanTask(task) {
  try {
    await api.post('/rescan', { task_id: task.task_id })
    task.status = 'processing'
    task.progress = 0
    toastStore.success(`"${task.filename}" 已重新扫描`)
  } catch (err) {
    if (err.response?.status === 404) {
      // Task lost from memory (container restart) — remove stale entry
      taskStore.tasks = taskStore.tasks.filter(t => t.task_id !== task.task_id)
      toastStore.warning(`"${task.filename}" 任务已过期，请重新上传文件`)
    } else {
      toastStore.error('重新扫描失败')
    }
  }
}

// --- Delete ---
async function deleteSelected() {
  if (selectedIds.value.size === 0) return

  const toDelete = []
  let lockedSkipped = 0

  for (const id of selectedIds.value) {
    if (isLocked(id)) {
      lockedSkipped++
    } else {
      toDelete.push(id)
    }
  }

  if (lockedSkipped > 0 && toDelete.length === 0) {
    toastStore.error(lockedSkipped + " 条任务已锁定，跳过")
    return
  }

  if (lockedSkipped > 0) {
    toastStore.error(lockedSkipped + " 条任务已锁定，跳过")
  }

  if (toDelete.length === 0) return

  try {
    await api.post("/tasks/delete", { task_ids: toDelete })
    const deleteSet = new Set(toDelete)
    taskStore.tasks = taskStore.tasks.filter((t) => !deleteSet.has(t.task_id))
    // Remove deleted from selection
    const s = new Set(selectedIds.value)
    for (const id of toDelete) s.delete(id)
    selectedIds.value = s
    toastStore.success("已清除 " + toDelete.length + " 条任务")
  } catch {
    toastStore.error("删除失败")
  }
}

// --- Lifecycle ---
onMounted(() => {
  taskStore.startPolling()
})

onUnmounted(() => {
  taskStore.stopPolling()
})

// --- Status config ---
const statusConfig = {
  processing: { label: '处理中', bg: 'bg-blue-100', text: 'text-blue-800', dot: 'bg-blue-500' },
  completed:  { label: '已完成', bg: 'bg-green-100', text: 'text-green-800', dot: 'bg-green-500' },
  failed:     { label: '失败',   bg: 'bg-red-100',   text: 'text-red-800',   dot: 'bg-red-500' },
}

function getConfig(status) {
  return statusConfig[status] || statusConfig.processing
}

// --- formatTime ---
function formatTime(timestamp) {
  if (!timestamp) return '\u2014'
  let d
  if (typeof timestamp === 'number') {
    d = new Date(timestamp * 1000)
  } else if (typeof timestamp === 'string') {
    d = new Date(timestamp.endsWith('Z') || timestamp.includes('+') ? timestamp : timestamp + 'Z')
  } else {
    return '\u2014'
  }
  if (isNaN(d.getTime())) return '\u2014'
  return d.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  })
}

// --- Click outside to close dropdown ---
function onDropdownOverlayClick() {
  showCleanSetting.value = false
}
</script>

<template>
  <div class="w-full">
    <!-- Header -->
    <div class="flex items-center justify-between mb-3">
      <h2 class="text-lg font-semibold text-gray-800">任务列表</h2>
      <div class="flex items-center gap-3">
        <span class="text-xs text-gray-500">每 2 秒自动刷新</span>

        <!-- Delete button (only when selected) -->
        <button
          v-if="selectedIds.size > 0"
          class="inline-flex items-center gap-1 text-xs text-red-500 hover:text-red-700 transition-colors font-medium"
          @click="deleteSelected"
        >
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
          </svg>
          清除选中 ({{ selectedIds.size }})
        </button>

        <!-- Auto-clean setting -->
        <div class="relative">
          <!-- Backdrop to catch outside clicks -->
          <div
            v-if="showCleanSetting"
            class="fixed inset-0 z-10"
            @click="onDropdownOverlayClick"
          />
          <button
            class="relative z-20 text-xs text-gray-400 hover:text-gray-600 transition-colors flex items-center gap-1"
            @click.stop="showCleanSetting = !showCleanSetting"
          >
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            自动清理
          </button>
          <div
            v-if="showCleanSetting"
            class="absolute right-0 top-full mt-1 bg-white border rounded-lg shadow-lg p-3 z-30 w-52"
          >
            <label class="text-xs text-gray-600 block mb-2">超过指定天数的任务自动隐藏</label>
            <select
              v-model.number="autoCleanDays"
              class="w-full border rounded px-2 py-1 text-sm"
            >
              <option :value="0">关闭</option>
              <option :value="1">1 天</option>
              <option :value="3">3 天</option>
              <option :value="7">7 天</option>
              <option :value="14">14 天</option>
              <option :value="30">30 天</option>
            </select>
            <p v-if="autoCleanDays > 0" class="text-xs text-green-600 mt-1.5">
              ✓ 超过 {{ autoCleanDays }} 天的任务已自动隐藏
            </p>
          </div>
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div
      v-if="displayTasks.length === 0"
      class="text-center py-12 text-gray-400 bg-white rounded-xl border"
    >
      <svg class="w-10 h-10 mx-auto mb-2 opacity-40" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
      <p>暂无任务，请上传文件</p>
    </div>

    <!-- Task table -->
    <div v-else class="bg-white rounded-xl border overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="bg-gray-50 border-b">
              <!-- Checkbox header -->
              <th class="w-10 px-3 py-3">
                <input
                  type="checkbox"
                  class="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500 cursor-pointer"
                  :checked="allPageSelected"
                  :indeterminate="somePageSelected"
                  @change="toggleSelectAllPage"
                />
              </th>
              <th class="text-left px-4 py-3 font-semibold text-gray-600">文件名</th>
              <th class="text-left px-4 py-3 font-semibold text-gray-600">状态</th>
              <th class="text-left px-4 py-3 font-semibold text-gray-600">检测结果</th>
              <th class="text-left px-4 py-3 font-semibold text-gray-600 hidden sm:table-cell">进度</th>
              <th class="text-left px-4 py-3 font-semibold text-gray-600 hidden md:table-cell">创建时间</th>
              <th class="text-left px-4 py-3 font-semibold text-gray-600 hidden lg:table-cell">任务 ID</th>
              <th class="text-left px-4 py-3 font-semibold text-gray-600">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-100">
            <tr
              v-for="task in pagedTasks"
              :key="task.task_id"
              class="hover:bg-gray-50 transition-colors"
              :class="{
                'bg-blue-50/40': selectedIds.has(task.task_id),
                'border-l-2 border-amber-400': isLocked(task.task_id),
              }"
            >
              <!-- Checkbox -->
              <td class="w-10 px-3 py-3">
                <input
                  type="checkbox"
                  class="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500 cursor-pointer"
                  :checked="selectedIds.has(task.task_id)"
                  @change="toggleSelect(task.task_id)"
                />
              </td>

              <!-- Filename + Rescan -->
              <td class="px-4 py-3 max-w-[240px]">
                <div class="flex items-center gap-1.5">
                  <span class="font-medium text-gray-800 truncate">{{ task.filename }}</span>
                  <button
                    v-if="task.status === 'completed'"
                    class="flex-shrink-0 p-1 text-gray-300 hover:text-blue-500 rounded hover:bg-blue-50 transition-colors"
                    title="重新扫描"
                    @click.stop="rescanTask(task)"
                  >
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182" />
                    </svg>
                  </button>
                </div>
              </td>

              <!-- Status badge -->
              <td class="px-4 py-3 whitespace-nowrap">
                <span
                  class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium"
                  :class="[getConfig(task.status).bg, getConfig(task.status).text]"
                >
                  <span
                    class="w-1.5 h-1.5 rounded-full"
                    :class="[
                      getConfig(task.status).dot,
                      task.status === 'processing' ? 'animate-pulse' : '',
                    ]"
                  />
                  {{ getConfig(task.status).label }}
                </span>
              </td>

              <!-- PII detection result -->
              <td class="px-4 py-3 whitespace-nowrap">
                <template v-if="task.status === 'completed'">
                  <span
                    v-if="(task.total_pii || 0) > 0"
                    class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700"
                  >
                    <svg class="w-3 h-3" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
                    </svg>
                    {{ task.total_pii }} 项
                  </span>
                  <span
                    v-else-if="(task.text_segments || 0) > 0"
                    class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700"
                  >
                    <svg class="w-3 h-3" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                    安全
                  </span>
                  <span v-else class="text-xs text-gray-300">—</span>
                </template>
                <span v-else class="text-xs text-gray-300">—</span>
              </td>

              <!-- Progress bar -->
              <td class="px-4 py-3 hidden sm:table-cell">
                <div class="flex items-center gap-2">
                  <div class="w-24 bg-gray-200 rounded-full h-1.5 overflow-hidden">
                    <div
                      class="h-full rounded-full transition-all duration-500"
                      :class="task.status === 'failed' ? 'bg-red-400' : 'bg-blue-500'"
                      :style="{ width: task.progress + '%' }"
                    />
                  </div>
                  <span class="text-xs text-gray-500 font-mono w-10">
                    {{ Math.round(task.progress) }}%
                  </span>
                </div>
              </td>

              <!-- Created at -->
              <td class="px-4 py-3 text-gray-500 hidden md:table-cell">
                {{ formatTime(task.created_at) }}
              </td>

              <!-- Task ID (truncated) -->
              <td class="px-4 py-3 text-gray-400 font-mono text-xs hidden lg:table-cell">
                {{ task.task_id.slice(0, 8) }}…
              </td>

              <!-- Actions -->
              <td class="px-4 py-3 whitespace-nowrap">
                <div class="flex items-center gap-2">
                  <!-- View result button -->
                  <button
                    v-if="task.status === 'completed'"
                    class="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-blue-600 bg-blue-50 rounded-lg hover:bg-blue-100 transition-colors"
                    @click="emit('viewResult', task.task_id)"
                  >
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                      <path stroke-linecap="round" stroke-linejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                    </svg>
                    查看结果
                  </button>
                  <span v-else class="text-xs text-gray-300">—</span>

                  <!-- Lock toggle -->
                  <button
                    class="p-1 rounded hover:bg-gray-100 transition-colors"
                    :title="isLocked(task.task_id) ? '解锁任务' : '锁定任务'"
                    @click="toggleLock(task.task_id)"
                  >
                    <!-- Locked (filled) -->
                    <svg
                      v-if="isLocked(task.task_id)"
                      class="w-4 h-4 text-amber-500"
                      fill="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                    </svg>
                    <!-- Unlocked (outline) -->
                    <svg
                      v-else
                      class="w-4 h-4 text-gray-400"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="1.5"
                      viewBox="0 0 24 24"
                    >
                      <path stroke-linecap="round" stroke-linejoin="round" d="M8 11V7a4 4 0 118 0m-4 8v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2z" />
                    </svg>
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Select all across pages link -->
      <div
        v-if="selectedIds.size > 0 && displayTasks.length > PAGE_SIZE"
        class="px-4 py-2 border-t bg-gray-50/50 text-xs text-gray-500 flex items-center gap-2"
      >
        <span>已选 {{ selectedIds.size }} 条</span>
        <button
          v-if="selectedIds.size < displayTasks.length"
          class="text-blue-500 hover:text-blue-700 underline"
          @click="selectAllAcrossPages"
        >
          全选 {{ displayTasks.length }} 条
        </button>
      </div>

      <!-- Pagination -->
      <div
        v-if="totalPages > 1"
        class="flex items-center justify-center gap-4 px-4 py-3 border-t bg-gray-50/50"
      >
        <button
          class="text-xs text-gray-500 hover:text-gray-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          :disabled="currentPage <= 1"
          @click="prevPage"
        >
          &lt; 上一页
        </button>
        <span class="text-xs text-gray-500 font-mono">
          {{ currentPage }}/{{ totalPages }}
        </span>
        <button
          class="text-xs text-gray-500 hover:text-gray-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          :disabled="currentPage >= totalPages"
          @click="nextPage"
        >
          下一页 &gt;
        </button>
      </div>
    </div>
  </div>
</template>
