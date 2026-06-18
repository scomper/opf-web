# OPF-Web 集成 privacy-filter.cpp 实施计划

> 2026-06-17 · POC 验证通过，推理 8-20ms，中文 PII 检测效果好

## 架构变更

**当前**：双容器（app.py → HTTP → server.py/PyTorch，合计 11GB 内存）
**目标**：单容器（app.py 本地调用 pf_backend.py/ctypes，~3.5GB 内存）

```
┌──────────────────────────────────────────────────────┐
│   单容器（合并后）                                      │
│   app.py (FastAPI :8081)                               │
│     ├── pf_backend.py ← 新建，ctypes wrapper          │
│     │     ├── libpf.so + libggml.so (~7MB)            │
│     │     └── privacy-filter-multilingual-f16.gguf    │
│     │         (2.7GB，首次启动从 HuggingFace 下载)      │
│     ├── OCR (OnnxOCR, det_limit_side_len=640, 不变)   │
│     └── 后处理 (白名单/正则/误报过滤, 适配新标签)        │
│   预估：内存 ~3.5GB / 镜像 ~1.5GB                      │
└──────────────────────────────────────────────────────┘
```

## 变更清单

### 新建文件

| 文件 | 行数 | 说明 |
|------|------|------|
| `pf_backend.py` | ~200 | ctypes 绑定 + 标签映射 + 合并逻辑 + 线程安全单例 |

### 修改文件

| 文件 | 位置 | 改动 |
|------|------|------|
| `server.py` | 全文替换 | 从 PyTorch OPF → 调用 pf_backend.classify() |
| `app.py` | L1004-1009 | `detect_pii_batch()` 改为本地调用（去掉 HTTP） |
| `app.py` | L1041-1230 | `_is_false_positive()` 标签名适配 |
| `app.py` | L1028-1034 | `_space_sensitive_labels` 更新 |
| `app.py` | L1633-1640 | `LABEL_ZH` 添加新类别中文名 |
| `Dockerfile` | 全文重写 | CMake 编译 + 单容器 |
| `docker-compose.yml` | 删除 opf 服务 | 只保留一个服务 |

### 删除/弃用

| 文件 | 说明 |
|------|------|
| `Dockerfile.opf` | 不再需要 PyTorch 容器 |
| `requirements.txt` | 去掉 `opf`、`torch`、`transformers` 依赖 |

## 实施步骤

### Phase 1：pf_backend.py（核心）

新建 `pf_backend.py`，包含：

1. **C API 绑定**（基于 POC 验证的 ctypes 代码）
   - `PFEntity` 结构体
   - `pf_load` / `pf_classify` / `pf_free` / `pf_entities_free` / `pf_set_window`
   - 字节偏移 → 字符偏移转换

2. **标签映射表**（217 → 8 类）

   ```
   FIRSTNAME/MIDDLENAME/LASTNAME → private_person
   PHONE                         → private_phone
   EMAIL                         → private_email
   URL/IPADDRESS                 → private_url
   STREET/CITY/STATE/ZIPCODE/... → private_address
   DATE/DATEOFBIRTH              → private_date
   SSN/ACCOUNTNAME/IBAN/...      → account_number
   CREDITCARD/BANKACCOUNT        → private_bankcard
   PASSWORD/CVV/PIN              → secret
   ORGANIZATION                  → organization
   AMOUNT/CURRENCY/GENDER/AGE... → 丢弃（非 PII）
   ```

3. **相邻同类型实体合并**
   - FIRSTNAME("靳晓") + LASTNAME("鹏") → private_person("靳晓鹏")
   - STREET("沙子口路甲") + BUILDINGNUMBER("48号") → private_address("沙子口路甲48号")
   - max_gap=1 字符内同类型自动合并

4. **线程安全**
   - 单例模式（`PFBackend.get()`）
   - `threading.Lock()` 保护 classify 调用（GGML 非线程安全，但推理仅 8-20ms）

5. **对外接口**
   ```python
   pf = PFBackend.get()
   spans = pf.classify("文本内容", threshold=0.5)
   # → [{"label": "private_person", "start": 0, "end": 3, "text": "张三", "score": 0.95}]
   ```

### Phase 2：server.py 替换

将 `server.py` 从 PyTorch OPF 改为调用 pf_backend：

```python
# 改前
from opf._api import OPF
_redactor = OPF(device="cpu")
result = _redactor.redact(text)

# 改后
from pf_backend import PFBackend
_pf = PFBackend.get()
spans = _pf.classify(text, threshold=0.5)
```

输出格式对齐：`detected_spans: list[dict]`，每个 span 包含 `{label, start, end, text, placeholder}`

### Phase 3：app.py 适配

最小化改动，只改标签相关的判断逻辑：

1. **`_is_false_positive()`** — 标签名大写变小写映射
2. **`_space_sensitive_labels`** — 添加新标签
3. **`LABEL_ZH`** — 新增中文显示名

### Phase 4：Docker 化

```dockerfile
FROM ubuntu:22.04 AS builder
RUN apt-get update && apt-get install -y cmake g++ git
COPY privacy-filter.cpp /build/pf
RUN cd /build/pf && cmake --preset release-portable \
    && cmake --build --preset release-portable -j

FROM python:3.12-slim
RUN apt-get update && apt-get install -y libgl1 libglib2.0-0 fonts-noto-cjk
COPY --from=builder /build/pf/build/release-portable/bin/libpf.so /usr/local/lib/pf/
COPY --from=builder /build/pf/build/release-portable/bin/libggml*.so /usr/local/lib/pf/
COPY --from=builder /build/pf/build/release-portable/bin/libggml-cpu-*.so /usr/local/lib/pf/
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# 模型：首次启动自动下载，或用 volume 挂载预下载的模型
ENV PF_MODEL_PATH=/models/privacy-filter-multilingual-f16.gguf
EXPOSE 8081
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8081"]
```

### Phase 5：测试验证

1. **精度对比**：用 OPF 原始测试集跑一遍，对比检测结果
2. **中文 PII 测试**：身份证、手机、邮箱、地址、银行卡
3. **性能测试**：单条延迟、批量吞吐
4. **集成测试**：前端上传文件 → 检测 → 脱敏 → 下载，端到端验证

## 风险与应对

| 风险 | 概率 | 应对 |
|------|------|------|
| 标签映射导致精度下降 | 中 | Phase 5 回归测试 + 保留正则补充检测 |
| GGML 在 Docker (x86_64) 编译问题 | 低 | POC 已验证 ARM，Docker 需验证 x86 |
| 模型 2.7GB 下载慢 | 中 | 支持 volume 挂载 + 启动时检查 |
| 线程安全问题 | 低 | Lock 保护 + 推理耗时极短 |

## 预期收益

| 维度 | 改前 | 改后 |
|------|------|------|
| 内存 | ~11GB（两容器） | ~3.5GB（单容器） |
| 镜像 | ~11GB | ~1.5GB |
| 推理速度 | ~200-500ms | ~8-20ms（25×） |
| 依赖 | Python + PyTorch + Transformers | C++ dylib + ctypes |
| 长文档 | OOM 风险 | 支持 131k token |
