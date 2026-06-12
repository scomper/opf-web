<script setup>
import { ref } from 'vue'
import { useTaskStore } from '../stores/taskStore'
import { useToastStore } from '../stores/toastStore'

const taskStore = useTaskStore()
const toastStore = useToastStore()

const ALLOWED_EXTENSIONS = new Set(['.docx', '.pdf', '.csv', '.xlsx', '.txt', '.md'])
const EXT_LABEL = 'docx, pdf, csv, xlsx, txt, md'

const isDragging = ref(false)
const fileInput = ref(null)
const uploadQueue = ref([]) // { id, file, progress, status }
let nextQueueId = 0

function getExtension(filename) {
  const idx = filename.lastIndexOf('.')
  return idx >= 0 ? filename.slice(idx).toLowerCase() : ''
}

function validateFile(file) {
  const ext = getExtension(file.name)
  if (!ALLOWED_EXTENSIONS.has(ext)) {
    toastStore.error(`不支持的文件格式 "${ext}"，仅允许 ${EXT_LABEL}`)
    return false
  }
  return true
}

function addFiles(fileList) {
  const files = Array.from(fileList)
  const validFiles = []

  for (const file of files) {
    if (validateFile(file)) {
      validFiles.push(file)
    }
  }

  if (validFiles.length === 0) return

  // Add to queue
  const entries = validFiles.map((file) => ({
    id: nextQueueId++,
    file,
    progress: 0,
    status: 'queued', // queued | uploading | done | error
  }))
  uploadQueue.value.push(...entries)

  // Start processing the queue
  processQueue()
}

async function processQueue() {
  // Find next queued item
  const next = uploadQueue.value.find((e) => e.status === 'queued')
  if (!next) return

  next.status = 'uploading'

  try {
    await taskStore.uploadFile(next.file, (pct) => {
      next.progress = pct
    })
    next.status = 'done'
    next.progress = 100
    toastStore.success(`"${next.file.name}" 上传成功`)
    scheduleRemoval(next.id)
  } catch {
    next.status = 'error'
    // interceptor already shows error toast
  }

  // Process next in queue (sequential)
  processQueue()
}

function onDragOver(e) {
  e.preventDefault()
  isDragging.value = true
}

function onDragLeave(e) {
  e.preventDefault()
  isDragging.value = false
}

function onDrop(e) {
  e.preventDefault()
  isDragging.value = false
  if (e.dataTransfer?.files?.length) {
    addFiles(e.dataTransfer.files)
  }
}

function onFileInputChange(e) {
  if (e.target.files?.length) {
    addFiles(e.target.files)
    // Reset so same file can be selected again
    e.target.value = ''
  }
}

function openFilePicker() {
  fileInput.value?.click()
}

// Auto-dissolve completed entries after 1.5s
function scheduleRemoval(entryId) {
  setTimeout(() => {
    const idx = uploadQueue.value.findIndex(e => e.id === entryId)
    if (idx !== -1) uploadQueue.value.splice(idx, 1)
  }, 1500)
}
</script>

<template>
  <div class="w-full">
    <!-- Drop Zone -->
    <div
      class="relative border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors duration-200"
      :class="
        isDragging
          ? 'border-blue-500 bg-blue-50'
          : 'border-gray-300 bg-white hover:border-blue-400 hover:bg-blue-50/30'
      "
      @dragover="onDragOver"
      @dragleave="onDragLeave"
      @drop="onDrop"
      @click="openFilePicker"
    >
      <input
        ref="fileInput"
        type="file"
        multiple
        accept=".docx,.pdf,.csv,.xlsx,.txt,.md"
        class="hidden"
        @change="onFileInputChange"
      />

      <div class="flex flex-col items-center gap-3">
        <!-- Upload icon -->
        <svg
          class="w-12 h-12"
          :class="isDragging ? 'text-blue-500' : 'text-gray-400'"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="1.5"
            d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
          />
        </svg>

        <div>
          <p class="text-base font-medium" :class="isDragging ? 'text-blue-700' : 'text-gray-700'">
            {{ isDragging ? '松开鼠标上传文件' : '拖拽文件到此处，或点击选择' }}
          </p>
          <p class="text-sm text-gray-500 mt-1">
            支持格式：{{ EXT_LABEL }}（最大 50MB）
          </p>
        </div>
      </div>
    </div>

    <!-- Upload Queue -->
    <div v-if="uploadQueue.length > 0" class="mt-4 space-y-2">
      <h3 class="text-sm font-semibold text-gray-600 mb-2">上传队列</h3>
      <TransitionGroup name="dissolve">
        <div
          v-for="entry in uploadQueue"
          :key="entry.id"
          class="flex items-center gap-3 bg-white rounded-lg border px-4 py-3"
        >
        <!-- Status icon -->
        <div class="flex-shrink-0">
          <span v-if="entry.status === 'done'" class="text-green-500 text-lg">✓</span>
          <span v-else-if="entry.status === 'error'" class="text-red-500 text-lg">✗</span>
          <svg
            v-else
            class="animate-spin h-5 w-5 text-blue-500"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle
              class="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              stroke-width="4"
            />
            <path
              class="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
            />
          </svg>
        </div>

        <!-- File info + progress -->
        <div class="flex-1 min-w-0">
          <p class="text-sm font-medium text-gray-800 truncate">{{ entry.file.name }}</p>
          <div class="mt-1 w-full bg-gray-200 rounded-full h-2 overflow-hidden">
            <div
              class="h-full rounded-full transition-all duration-300"
              :class="entry.status === 'error' ? 'bg-red-400' : 'bg-blue-500'"
              :style="{ width: entry.progress + '%' }"
            />
          </div>
        </div>

        <!-- Percentage -->
        <span class="text-xs font-mono text-gray-500 w-10 text-right">
          {{ entry.progress }}%
        </span>
      </div>
      </TransitionGroup>
    </div>
  </div>
</template>

<style scoped>
.dissolve-leave-active {
  transition: all 0.8s ease-out;
}
.dissolve-leave-to {
  opacity: 0;
  transform: translateX(30px);
  max-height: 0;
  margin-top: 0;
  margin-bottom: 0;
  padding-top: 0;
  padding-bottom: 0;
  overflow: hidden;
}
</style>
