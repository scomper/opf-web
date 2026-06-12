<script setup>
import { ref } from 'vue'
import FileUploadZone from './components/FileUploadZone.vue'
import TaskList from './components/TaskList.vue'
import ToastContainer from './components/ToastContainer.vue'
import ResultView from './components/ResultView.vue'
import SettingsPanel from './components/SettingsPanel.vue'

const viewingTaskId = ref(null)
const showSettings = ref(false)

function viewResult(taskId) {
  viewingTaskId.value = taskId
}

function switchTask(taskId) {
  viewingTaskId.value = taskId
}

function backToList() {
  viewingTaskId.value = null
}
</script>

<template>
  <div class="min-h-screen bg-gray-50">
    <!-- Toast notifications -->
    <ToastContainer />

    <!-- Header -->
    <header class="bg-white border-b shadow-sm">
      <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
        <div class="flex items-center gap-3">
          <div class="flex items-center justify-center w-9 h-9 rounded-lg bg-blue-600">
            <svg class="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"
              />
            </svg>
          </div>
          <div class="flex-1">
            <h1 class="text-xl font-bold text-gray-900">OPF 隐私信息检测平台</h1>
            <p class="text-sm text-gray-500">上传文档，自动检测并脱敏隐私信息</p>
          </div>
          <button
            class="flex items-center gap-1.5 px-3 py-2 text-sm text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
            @click="showSettings = true"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            检测配置
          </button>
        </div>
      </div>
    </header>

    <!-- Settings Panel -->
    <SettingsPanel v-if="showSettings" @close="showSettings = false" />

    <!-- Main Content -->
    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <!-- Result View -->
      <ResultView
        v-if="viewingTaskId"
        :task-id="viewingTaskId"
        @back="backToList"
        @switch-task="switchTask"
      />

      <!-- Upload + Task List -->
      <div v-else class="space-y-6">
        <!-- Upload Zone (top, compact) -->
        <div>
          <h2 class="text-lg font-semibold text-gray-800 mb-3">上传文件</h2>
          <FileUploadZone />
        </div>

        <!-- Task List (full width) -->
        <TaskList @view-result="viewResult" />
      </div>
    </main>
  </div>
</template>
