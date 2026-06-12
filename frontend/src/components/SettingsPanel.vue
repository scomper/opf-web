<script setup>
import { ref, onMounted } from 'vue'
import { useToastStore } from '../stores/toastStore'
import api from '../api/axios'

const emit = defineEmits(['close'])
const toastStore = useToastStore()

const activeTab = ref('whitelist')
const whitelistRules = ref([])
const dictionaryWords = ref([])
const loading = ref(false)

// New rule/word form
const newPattern = ref('')
const newWord = ref('')
const newWordType = ref('private_person')

const wordTypes = [
  { value: 'private_person', label: '姓名' },
  { value: 'private_phone', label: '手机号码' },
  { value: 'private_email', label: '电子邮箱' },
  { value: 'account_number', label: '账号/证件号' },
  { value: 'private_address', label: '地址' },
  { value: 'secret', label: '密码/密钥' },
]

onMounted(async () => {
  loading.value = true
  try {
    const [wl, dc] = await Promise.all([
      api.get('/whitelist'),
      api.get('/dictionary'),
    ])
    whitelistRules.value = wl.data.rules || []
    dictionaryWords.value = dc.data.words || []
  } catch {
    toastStore.error('加载配置失败')
  } finally {
    loading.value = false
  }
})

async function saveWhitelist() {
  try {
    await api.post('/whitelist', { rules: whitelistRules.value })
    toastStore.success('白名单已保存')
  } catch {
    toastStore.error('保存失败')
  }
}

async function saveDictionary() {
  try {
    await api.post('/dictionary', { words: dictionaryWords.value })
    toastStore.success('敏感词库已保存')
  } catch {
    toastStore.error('保存失败')
  }
}

function addRule() {
  const p = newPattern.value.trim()
  if (!p) return
  whitelistRules.value.push({ pattern: p, reason: '手动添加' })
  newPattern.value = ''
}

function removeRule(idx) {
  whitelistRules.value.splice(idx, 1)
}

function addWord() {
  const w = newWord.value.trim()
  if (!w) return
  dictionaryWords.value.push({ text: w, type: newWordType.value })
  newWord.value = ''
}

function removeWord(idx) {
  dictionaryWords.value.splice(idx, 1)
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/30" @click.self="emit('close')">
    <div class="bg-white rounded-2xl shadow-xl w-full max-w-lg max-h-[80vh] flex flex-col overflow-hidden">
      <!-- Header -->
      <div class="flex items-center justify-between px-6 py-4 border-b">
        <h2 class="text-lg font-semibold text-gray-800">检测配置</h2>
        <button class="text-gray-400 hover:text-gray-600" @click="emit('close')">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <!-- Tabs -->
      <div class="flex border-b">
        <button
          class="flex-1 py-3 text-sm font-medium transition-colors"
          :class="activeTab === 'whitelist' ? 'text-blue-600 border-b-2 border-blue-600' : 'text-gray-500 hover:text-gray-700'"
          @click="activeTab = 'whitelist'"
        >
          白名单
        </button>
        <button
          class="flex-1 py-3 text-sm font-medium transition-colors"
          :class="activeTab === 'dictionary' ? 'text-blue-600 border-b-2 border-blue-600' : 'text-gray-500 hover:text-gray-700'"
          @click="activeTab = 'dictionary'"
        >
          敏感词库
        </button>
      </div>

      <!-- Content -->
      <div class="flex-1 overflow-y-auto p-6">
        <!-- Whitelist tab -->
        <div v-if="activeTab === 'whitelist'">
          <p class="text-xs text-gray-500 mb-4">白名单中的正则表达式匹配到的内容将被跳过检测，不会标记为敏感信息。</p>

          <!-- Add rule -->
          <div class="flex gap-2 mb-4">
            <input
              v-model="newPattern"
              class="flex-1 border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="输入正则表达式（如 \d{4}年）"
              @keydown.enter="addRule"
            />
            <button class="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700" @click="addRule">
              添加
            </button>
          </div>

          <!-- Rule list -->
          <div class="space-y-2">
            <div
              v-for="(rule, idx) in whitelistRules"
              :key="idx"
              class="flex items-center gap-2 bg-gray-50 rounded-lg px-3 py-2"
            >
              <code class="flex-1 text-xs text-gray-700 break-all">{{ rule.pattern }}</code>
              <button class="text-gray-400 hover:text-red-500 flex-shrink-0" @click="removeRule(idx)">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </button>
            </div>
            <p v-if="whitelistRules.length === 0" class="text-sm text-gray-400 text-center py-4">暂无白名单规则</p>
          </div>

          <button
            class="mt-4 w-full py-2 bg-green-600 text-white text-sm rounded-lg hover:bg-green-700"
            @click="saveWhitelist"
          >
            保存白名单
          </button>
        </div>

        <!-- Dictionary tab -->
        <div v-if="activeTab === 'dictionary'">
          <p class="text-xs text-gray-500 mb-4">自定义敏感词将在检测时作为补充规则，匹配到的内容会被标记为对应类型。</p>

          <!-- Add word -->
          <div class="flex gap-2 mb-4">
            <input
              v-model="newWord"
              class="flex-1 border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="输入敏感词"
              @keydown.enter="addWord"
            />
            <select
              v-model="newWordType"
              class="border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option v-for="t in wordTypes" :key="t.value" :value="t.value">{{ t.label }}</option>
            </select>
            <button class="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700" @click="addWord">
              添加
            </button>
          </div>

          <!-- Word list -->
          <div class="space-y-2">
            <div
              v-for="(word, idx) in dictionaryWords"
              :key="idx"
              class="flex items-center gap-2 bg-gray-50 rounded-lg px-3 py-2"
            >
              <span class="flex-1 text-sm text-gray-800">{{ word.text }}</span>
              <span class="text-xs text-gray-500 bg-gray-200 px-2 py-0.5 rounded">
                {{ wordTypes.find(t => t.value === word.type)?.label || word.type }}
              </span>
              <button class="text-gray-400 hover:text-red-500 flex-shrink-0" @click="removeWord(idx)">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </button>
            </div>
            <p v-if="dictionaryWords.length === 0" class="text-sm text-gray-400 text-center py-4">暂无自定义敏感词</p>
          </div>

          <button
            class="mt-4 w-full py-2 bg-green-600 text-white text-sm rounded-lg hover:bg-green-700"
            @click="saveDictionary"
          >
            保存词库
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
