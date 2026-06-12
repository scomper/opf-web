import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '../api/axios'

export const useTaskStore = defineStore('task', () => {
  /** @type {import('vue').Ref<Array>} */
  const tasks = ref([])
  const loading = ref(false)
  let pollTimer = null

  /**
   * Upload a single file with progress tracking.
   * @param {File} file
   * @param {Function} onProgress - callback receiving 0-100
   * @returns {Promise<object>} upload response {task_id, status}
   */
  async function uploadFile(file, onProgress) {
    const formData = new FormData()
    formData.append('file', file)

    const response = await api.post('/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (event) => {
        if (event.total) {
          const pct = Math.round((event.loaded * 100) / event.total)
          onProgress?.(pct)
        }
      },
    })

    // Refresh task list immediately after upload
    await fetchTasks()
    return response.data
  }

  /**
   * Fetch all tasks from the server via /api/tasks.
   */
  async function fetchTasks() {
    try {
      const response = await api.get('/tasks')
      tasks.value = response.data
    } catch {
      // interceptor already shows toast
    }
  }

  /**
   * Start polling /api/tasks every 2 seconds.
   */
  function startPolling() {
    stopPolling()
    fetchTasks()
    pollTimer = setInterval(fetchTasks, 2000)
  }

  /**
   * Stop polling.
   */
  function stopPolling() {
    if (pollTimer !== null) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  return {
    tasks,
    loading,
    uploadFile,
    fetchTasks,
    startPolling,
    stopPolling,
  }
})
