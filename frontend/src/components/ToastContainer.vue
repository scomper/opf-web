<script setup>
import { useToastStore } from '../stores/toastStore'

const toast = useToastStore()

const typeClasses = {
  error: 'bg-red-500',
  success: 'bg-green-500',
  warning: 'bg-yellow-500 text-yellow-900',
  info: 'bg-blue-500',
}
</script>

<template>
  <div class="fixed top-4 right-4 z-50 flex flex-col gap-2 w-80">
    <TransitionGroup name="toast">
      <div
        v-for="t in toast.toasts"
        :key="t.id"
        class="flex items-start gap-2 px-4 py-3 rounded-lg shadow-lg text-white text-sm"
        :class="typeClasses[t.type] || typeClasses.info"
      >
        <span class="flex-1">{{ t.message }}</span>
        <button
          class="ml-2 opacity-70 hover:opacity-100 leading-none"
          @click="toast.removeToast(t.id)"
        >
          ✕
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition: all 0.3s ease;
}
.toast-enter-from {
  opacity: 0;
  transform: translateX(40px);
}
.toast-leave-to {
  opacity: 0;
  transform: translateX(40px);
}
</style>
