import { defineStore } from 'pinia'
import { ref } from 'vue'

let nextId = 0

export const useToastStore = defineStore('toast', () => {
  const toasts = ref([])

  function addToast(message, type = 'info', duration = 4000) {
    const id = nextId++
    toasts.value.push({ id, message, type })
    if (duration > 0) {
      setTimeout(() => removeToast(id), duration)
    }
  }

  function removeToast(id) {
    toasts.value = toasts.value.filter((t) => t.id !== id)
  }

  function error(message, duration) {
    addToast(message, 'error', duration)
  }

  function success(message, duration) {
    addToast(message, 'success', duration)
  }

  function warning(message, duration) {
    addToast(message, 'warning', duration)
  }

  function info(message, duration) {
    addToast(message, 'info', duration)
  }

  return { toasts, addToast, removeToast, error, success, warning, info }
})
