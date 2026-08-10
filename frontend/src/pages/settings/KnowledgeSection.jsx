import { useState, useEffect } from 'react';
import {
  FileText,
  FileSpreadsheet,
  Brain,
  Activity,
  Database,
  Search,
  RefreshCw,
  Network,
  HardDrive,
  AlertTriangle,
  Loader2,
  Check,
  Upload,
  Trash2,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAuth } from '@/lib/AuthContext';
import {
  listDocuments,
  uploadDocument,
  deleteDocument,
  deleteAllDocuments,
  searchKnowledge,
  importKnowledge,
} from '@/api/knowledge';
import {
  listEmbeddingModels,
  switchEmbeddingModel,
  getRagConfig,
  listGraphEntities,
} from '@/api/rag';
import EmbeddingSection from '@/components/SettingsSection/EmbeddingSection';

// 状态色（保存成功提示）
const SUCCESS_COLOR = 'oklch(0.7 0.09 145)';

/* ═══════════════════════════════════════════════════════════════
   4) 知识库（合并）— 文档 / 嵌入模型 / 系统状态 三合一
   - 顶部 Tab 切换（横向胶囊）
   - 文档 Tab：上传 + 列表 + 搜索
   - 嵌入模型 Tab：模型选择
   - 系统状态 Tab：RAG 总览
   ═══════════════════════════════════════════════════════════════ */
const KB_TABS = [
  { key: 'docs',      label: '文档管理',   icon: FileText },
  { key: 'embedding', label: '嵌入模型',   icon: Brain },
  { key: 'status',    label: '系统状态',   icon: Activity },
];

const KNOWLEDGE_ALLOWED_SOURCES = [
  'manual_upload',
  'public_web',
  'cached_snapshot',
  'official_api',
  'partner_api',
];

const KNOWLEDGE_SAMPLE_ROWS = [
  'content,category,scenario,title,external_id,data_source,source_url,source_note,tags',
  'RAGIMPORT-SAMPLE-001：青竹护肤晚 8 点直播间 GMV 环比增长 18.6%，应扩大晚 8 点到 10 点投放。,business_metric,live_ops,直播 GMV 复盘,manual-row-001,manual_upload,,运营手工整理,"GMV|直播|投放"',
  'RAGIMPORT-SAMPLE-002：公开网页整理显示，护肤达人筛选门槛为近 30 天互动率不低于 4.2%。,kol_strategy,public_research,KOL 公开资料,public-web-001,public_web,https://public-source.invalid/kol,公开网页整理,"KOL|公开资料"',
].join('\n');

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = '';
  let inQuotes = false;

  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    const next = text[i + 1];
    if (ch === '"' && inQuotes && next === '"') {
      cell += '"';
      i += 1;
      continue;
    }
    if (ch === '"') {
      inQuotes = !inQuotes;
      continue;
    }
    if (ch === ',' && !inQuotes) {
      row.push(cell.trim());
      cell = '';
      continue;
    }
    if ((ch === '\n' || ch === '\r') && !inQuotes) {
      if (ch === '\r' && next === '\n') i += 1;
      row.push(cell.trim());
      if (row.some(Boolean)) rows.push(row);
      row = [];
      cell = '';
      continue;
    }
    cell += ch;
  }

  row.push(cell.trim());
  if (row.some(Boolean)) rows.push(row);
  return rows;
}

function cleanText(value) {
  const text = String(value ?? '').trim();
  return text || undefined;
}

function normalizeKnowledgeItem(raw) {
  const tags = Array.isArray(raw.tags)
    ? raw.tags
    : String(raw.tags ?? '')
        .split('|')
        .map((tag) => tag.trim())
        .filter(Boolean);

  return {
    content: cleanText(raw.content),
    category: cleanText(raw.category) || 'general',
    scenario: cleanText(raw.scenario) || 'manual_import',
    title: cleanText(raw.title),
    external_id: cleanText(raw.external_id),
    data_source: cleanText(raw.data_source) || 'manual_upload',
    source_url: cleanText(raw.source_url),
    source_note: cleanText(raw.source_note),
    tags,
  };
}

function parseKnowledgeImportText(text) {
  const trimmed = text.trim();
  if (!trimmed) return [];

  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    const parsed = JSON.parse(trimmed);
    const rows = Array.isArray(parsed) ? parsed : parsed.items;
    if (!Array.isArray(rows)) throw new Error('JSON 需要是数组，或包含 items 数组');
    return rows.map(normalizeKnowledgeItem);
  }

  const rows = parseCsv(trimmed);
  if (rows.length < 2) throw new Error('CSV 至少需要表头和 1 行数据');
  const headers = rows[0].map((h) => h.trim());
  if (!headers.includes('content')) throw new Error('CSV 缺少必填列：content');

  return rows.slice(1).map((row) => {
    const raw = {};
    headers.forEach((header, idx) => {
      raw[header] = row[idx] ?? '';
    });
    return normalizeKnowledgeItem(raw);
  });
}

function validateKnowledgeItems(items) {
  const errors = [];
  items.forEach((item, index) => {
    const row = index + 1;
    if (!item.content) errors.push(`第 ${row} 行缺少 content`);
    if (!KNOWLEDGE_ALLOWED_SOURCES.includes(item.data_source)) {
      errors.push(`第 ${row} 行 data_source 不支持：${item.data_source}`);
    }
  });
  return errors;
}

function KbStatusBadge({ status }) {
  if (status === 'handling' || status === 'indexing') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-macaron-yellow px-2 py-0.5 text-[10px] font-medium text-foreground/80">
        <Loader2 className="size-2.5 animate-spin" />
        索引中
      </span>
    );
  }
  if (status === 'failed') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-macaron-rose px-2 py-0.5 text-[10px] font-medium text-foreground/80">
        <AlertTriangle className="size-2.5" />
        失败
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-macaron-mint px-2 py-0.5 text-[10px] font-medium text-foreground/80">
      <Check className="size-2.5" />
      已索引
    </span>
  );
}

function KbDocsTab() {
  const { user } = useAuth();
  const companyId = user?.company_id ? String(user.company_id) : '';

  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  // 上传进度：null 不显示；{ current, total, fileName } 显示进度条
  const [uploadProgress, setUploadProgress] = useState(null);
  const [drag, setDrag] = useState(false);
  const [error, setError] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState(null);
  const [searching, setSearching] = useState(false);
  const [importText, setImportText] = useState('');
  const [importPreview, setImportPreview] = useState([]);
  const [importResult, setImportResult] = useState(null);
  const [importing, setImporting] = useState(false);

  const loadDocs = async () => {
    setLoading(true);
    setError('');
    if (!companyId) {
      setDocs([]);
      setError('当前账号未关联公司，无法加载知识库文档');
      setLoading(false);
      return;
    }
    try {
      const data = await listDocuments(companyId);
      setDocs(data.documents || []);
    } catch (err) {
      setError(err.response?.data?.detail || '加载文档列表失败');
      console.error('加载文档列表失败:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadDocs(); }, [companyId]);

  const addFiles = async (fileList) => {
    if (!companyId) {
      setError('当前账号未关联公司，无法上传知识库文档');
      return;
    }
    const files = Array.from(fileList || []);
    if (files.length === 0) return;
    setUploading(true);
    setError('');

    // 先过滤合法文件，统计实际上传数量
    const valid = [];
    for (const file of files) {
      if (file.size > 10 * 1024 * 1024) {
        setError(`文件 ${file.name} 超过 10MB 限制`);
        continue;
      }
      const allowedExts = ['.pdf', '.docx', '.md', '.txt', '.markdown', '.html', '.htm'];
      const ext = '.' + file.name.split('.').pop().toLowerCase();
      if (!allowedExts.includes(ext)) {
        setError(`文件 ${file.name} 格式不支持`);
        continue;
      }
      valid.push(file);
    }

    for (let i = 0; i < valid.length; i++) {
      const file = valid[i];
      setUploadProgress({ current: i + 1, total: valid.length, fileName: file.name });
      try {
        await uploadDocument(file, companyId);
        await loadDocs();
      } catch (err) {
        setError(err.response?.data?.detail || `上传 ${file.name} 失败`);
        console.error('上传失败:', err);
      }
    }
    setUploadProgress(null);
    setUploading(false);
  };

  const removeDoc = async (doc) => {
    if (!companyId) {
      setError('当前账号未关联公司，无法删除知识库文档');
      return;
    }
    const docId = doc?.id;
    if (!docId) return;
    if (!window.confirm('确定要删除该文档吗？此操作会同步删除索引且不可撤销。')) return;
    try {
      await deleteDocument(docId, companyId);
      setDocs((prev) => prev.filter((d) => d.id !== docId));
    } catch (err) {
      setError(err.response?.data?.detail || '删除失败');
    }
  };

  const clearAll = async () => {
    if (!companyId) {
      setError('当前账号未关联公司，无法清空知识库');
      return;
    }
    if (!window.confirm('确定要清空知识库中的所有文档吗？此操作不可撤销。')) return;
    try {
      await deleteAllDocuments(companyId);
      setDocs([]);
    } catch (err) {
      setError(err.response?.data?.detail || '清空失败');
    }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    if (!companyId) {
      setError('当前账号未关联公司，无法搜索知识库');
      return;
    }
    setSearching(true);
    setSearchResults(null);
    try {
      const results = await searchKnowledge(searchQuery, companyId, 5);
      setSearchResults(results);
    } catch (err) {
      setError(err.response?.data?.detail || '搜索失败');
    } finally {
      setSearching(false);
    }
  };

  const parseImportItems = () => {
    const items = parseKnowledgeImportText(importText);
    const validationErrors = validateKnowledgeItems(items);
    if (validationErrors.length > 0) {
      throw new Error(validationErrors.slice(0, 5).join('；'));
    }
    return items;
  };

  const handlePreviewImport = () => {
    setError('');
    setImportResult(null);
    try {
      const items = parseImportItems();
      setImportPreview(items);
    } catch (err) {
      setImportPreview([]);
      setError(err.message || '导入内容解析失败');
    }
  };

  const handleKnowledgeImport = async (dryRun) => {
    setError('');
    setImportResult(null);
    setImporting(true);
    try {
      const items = parseImportItems();
      setImportPreview(items);
      const result = await importKnowledge(items, dryRun);
      setImportResult(result);
      if (!dryRun && items[0]?.content) {
        setSearchQuery(items[0].external_id || items[0].title || items[0].content.slice(0, 24));
      }
    } catch (err) {
      setError(err.response?.data?.detail || err.message || '结构化导入失败');
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {/* 搜索栏 */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="搜索知识库内容..."
            className="input-base h-9 w-full pl-9 pr-3 text-xs"
          />
        </div>
        <button
          type="button"
          onClick={handleSearch}
          disabled={searching || !searchQuery.trim()}
          className="btn btn-outline h-9 px-3 text-xs"
        >
          {searching ? <Loader2 className="size-3.5 animate-spin" /> : '搜索'}
        </button>
      </div>

      {/* 搜索结果 */}
      {searchResults !== null && (
        <div className="rounded-2xl border border-border bg-card p-4">
          <div className="mb-3 flex items-center justify-between">
            <p className="text-sm font-medium text-foreground">
              搜索结果 ({searchResults.length})
            </p>
            <button
              type="button"
              onClick={() => setSearchResults(null)}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              清除
            </button>
          </div>
          {searchResults.length === 0 ? (
            <p className="text-xs text-muted-foreground">未找到相关内容</p>
          ) : (
            <div className="flex flex-col gap-2">
              {searchResults.map((r, i) => (
                <div key={i} className="rounded-lg border border-border bg-background/40 p-3">
                  <p className="text-xs text-foreground">{r.content}</p>
                  <p className="mt-1 text-[10px] text-muted-foreground">
                    相似度: {r.distance != null ? (1 - r.distance).toFixed(3) : 'N/A'}
                    {r.metadata?.category && ` · 分类: ${r.metadata.category}`}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 结构化导入 */}
      <div className="rounded-2xl border border-border bg-card p-4">
        <div className="mb-3 flex items-start gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-secondary">
            <FileSpreadsheet className="size-4 text-foreground/80" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-foreground">结构化导入</p>
            <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
              没有企业 API 时，可粘贴 CSV / JSON 导入人工整理、公开网页或历史快照资料；正式导入会拒绝 mock / demo / seed。
            </p>
          </div>
          <button
            type="button"
            className="btn btn-outline h-8 px-3 text-xs"
            onClick={() => {
              setImportText(KNOWLEDGE_SAMPLE_ROWS);
              setImportResult(null);
              setImportPreview([]);
              setError('');
            }}
          >
            填入示例
          </button>
        </div>

        <textarea
          value={importText}
          onChange={(e) => {
            setImportText(e.target.value);
            setImportResult(null);
          }}
          rows={5}
          className="input-base min-h-28 w-full resize-y p-3 font-mono text-[11px] leading-relaxed"
          placeholder="粘贴 CSV：content,category,scenario,title,external_id,data_source,source_url,source_note,tags"
        />

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="btn btn-outline h-8 px-3 text-xs"
            onClick={handlePreviewImport}
            disabled={!importText.trim() || importing}
          >
            解析预览
          </button>
          <button
            type="button"
            className="btn btn-outline h-8 px-3 text-xs"
            onClick={() => handleKnowledgeImport(true)}
            disabled={!importText.trim() || importing}
          >
            {importing ? <Loader2 className="size-3 animate-spin" /> : '校验不写入'}
          </button>
          <button
            type="button"
            className="btn btn-primary h-8 px-3 text-xs"
            onClick={() => handleKnowledgeImport(false)}
            disabled={!importText.trim() || importing}
          >
            {importing ? <Loader2 className="size-3 animate-spin" /> : '正式导入'}
          </button>
        </div>

        {importPreview.length > 0 && (
          <div className="mt-3 rounded-xl border border-border bg-background/40 p-3">
            <p className="text-xs font-medium text-foreground">
              已解析 {importPreview.length} 条
            </p>
            <div className="mt-2 flex max-h-28 flex-col gap-1 overflow-y-auto scrollbar-thin">
              {importPreview.slice(0, 5).map((item, index) => (
                <p key={`${item.external_id || item.title || index}`} className="truncate text-[11px] text-muted-foreground">
                  {index + 1}. {item.data_source} · {item.category} · {item.content}
                </p>
              ))}
            </div>
          </div>
        )}

        {importResult && (
          <div className="mt-3 rounded-xl border border-macaron-mint/30 bg-macaron-mint/10 px-4 py-3 text-xs text-foreground/80">
            <p className="font-medium">
              {importResult.dry_run ? '校验通过' : '导入完成'}：新增 {importResult.imported} · 跳过 {importResult.skipped}
            </p>
            <p className="mt-1 text-[11px] text-muted-foreground">
              来源统计：{JSON.stringify(importResult.data_source_summary || {})}
            </p>
            {importResult.data_source_warning && (
              <p className="mt-1 text-[11px] text-muted-foreground">{importResult.data_source_warning}</p>
            )}
            {Array.isArray(importResult.errors) && importResult.errors.length > 0 && (
              <p className="mt-1 text-[11px] text-destructive">{importResult.errors.join('；')}</p>
            )}
          </div>
        )}
      </div>

      {/* 上传区 */}
      <label
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          addFiles(e.dataTransfer.files);
        }}
        className={cn(
          'flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed p-6 text-center transition-colors',
          drag
            ? 'border-primary bg-accent/40'
            : 'border-border bg-card hover:border-primary/40 hover:bg-accent/20'
        )}
      >
        <input
          type="file"
          multiple
          accept=".pdf,.docx,.md,.txt,.markdown,.html,.htm"
          className="hidden"
          onChange={(e) => addFiles(e.target.files)}
          disabled={uploading}
        />
        <div className="flex size-10 items-center justify-center rounded-2xl bg-macaron-blue">
          {uploading ? (
            <Loader2 className="size-4 animate-spin text-foreground/80" />
          ) : (
            <Upload className="size-4 text-foreground/80" />
          )}
        </div>
        <div>
          <p className="text-sm font-medium text-foreground">
            {uploading ? '正在上传...' : (
              <>拖拽文件到此处，或<span className="text-primary">点击选择文件</span></>
            )}
          </p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            单个文件不超过 10MB，支持 PDF / DOCX / Markdown / HTML / TXT
          </p>
        </div>
      </label>

      {/* 上传进度条 */}
      {uploadProgress && (
        <div
          className="rounded-xl border border-macaron-yellow/30 bg-macaron-yellow/10 px-4 py-3"
          role="status"
          aria-live="polite"
        >
          <div className="mb-1.5 flex items-center justify-between text-xs">
            <span className="flex min-w-0 items-center gap-1.5 font-medium text-foreground">
              <Loader2 className="size-3 shrink-0 animate-spin text-macaron-yellow" />
              <span className="truncate">正在上传：{uploadProgress.fileName}</span>
            </span>
            <span className="shrink-0 text-muted-foreground">
              {uploadProgress.current} / {uploadProgress.total}
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-secondary">
            <div
              className="h-full rounded-full bg-macaron-yellow transition-all"
              style={{
                width: `${Math.round((uploadProgress.current / uploadProgress.total) * 100)}%`,
              }}
            />
          </div>
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-macaron-rose bg-macaron-rose/5 px-4 py-3 text-xs text-foreground/80">
          <AlertTriangle className="size-3.5 shrink-0" style={{ color: 'var(--destructive)' }} />
          {error}
          <button
            type="button"
            onClick={() => setError('')}
            className="ml-auto text-muted-foreground hover:text-foreground"
          >
            关闭
          </button>
        </div>
      )}

      {/* 文件列表 */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium text-foreground">
            已上传文档 <span className="text-xs text-muted-foreground">（{docs.length}）</span>
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn btn-outline h-7 px-2 text-[11px]"
              onClick={loadDocs}
              disabled={loading}
            >
              <RefreshCw className={cn('size-3', loading && 'animate-spin')} />
            </button>
            <button
              type="button"
              className="btn btn-outline h-7 px-2.5 text-[11px]"
              onClick={clearAll}
              disabled={docs.length === 0}
            >
              清空全部
            </button>
          </div>
        </div>
        <ul className="flex max-h-72 flex-col divide-y divide-border overflow-y-auto rounded-2xl border border-border bg-card scrollbar-thin">
          {loading && (
            <li className="flex items-center justify-center gap-2 px-4 py-8 text-xs text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin" />
              加载中...
            </li>
          )}
          {!loading && docs.length === 0 && (
            <li className="flex flex-col items-center justify-center gap-3 px-4 py-10 text-center">
              <div className="flex size-14 items-center justify-center rounded-2xl bg-macaron-yellow/20">
                <FileText className="size-7 text-macaron-yellow" />
              </div>
              <div>
                <p className="text-sm font-medium text-foreground">暂无知识库</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  点击上方上传，或拖拽文件到此处
                </p>
              </div>
            </li>
          )}
          {!loading && docs.map((d) => (
            <li key={d.id} className="flex items-center gap-3 px-4 py-3">
              <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-secondary">
                <FileText className="size-4 text-foreground/80" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-foreground">{d.filename}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {d.chunks > 1 ? `${d.chunks} 个切片` : '1 个切片'}
                  {d.category && d.category !== 'general' && ` · ${d.category}`}
                </p>
              </div>
              <KbStatusBadge status={d.text_status} />
              <button
                type="button"
                onClick={() => removeDoc(d)}
                aria-label="删除"
                className="inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-destructive"
              >
                <Trash2 className="size-3.5" />
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function KbEmbeddingTab() {
  // 变更① T1.6：嵌入模式（local / api_*），由 EmbeddingSection 上报，控制本地模型列表的显隐
  const [mode, setMode] = useState('local');
  const [models, setModels] = useState([]);
  const [activeModel, setActiveModel] = useState('');
  const [loading, setLoading] = useState(true);
  const [switching, setSwitching] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');

  const loadModels = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await listEmbeddingModels();
      setModels(data.models || []);
      setActiveModel(data.active_model || '');
    } catch (err) {
      setError('加载嵌入模型列表失败');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadModels(); }, []);

  const handleSwitch = async (modelName) => {
    if (modelName === activeModel) return;
    setSwitching(true);
    setError('');
    try {
      await switchEmbeddingModel(modelName);
      setActiveModel(modelName);
      setSaved(true);
      setTimeout(() => setSaved(false), 1800);
    } catch (err) {
      setError(err.response?.data?.detail || '切换模型失败');
    } finally {
      setSwitching(false);
    }
  };

  const groups = {
    'BGE 系列': models.filter((m) => m.name.startsWith('bge')),
    'M3E 系列': models.filter((m) => m.name.startsWith('m3e')),
    'E5 系列': models.filter((m) => m.name.startsWith('e5')),
    '其他': models.filter((m) => !m.name.startsWith('bge') && !m.name.startsWith('m3e') && !m.name.startsWith('e5')),
  };

  return (
    <div className="flex flex-col gap-5">
      {/* 变更① T1.6：嵌入模式选择 + API 配置 + 测试 / 保存 */}
      <EmbeddingSection onModeChange={setMode} />

      {/* 本地模式：显示本地模型切换列表 */}
      {mode === 'local' && (
        <div className="border-t border-border pt-4">
          <p className="mb-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
            本地模型选择
          </p>

          {loading ? (
            <div className="flex items-center justify-center gap-2 py-8 text-xs text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              加载模型列表...
            </div>
          ) : (
            <>
              {error && (
                <div className="mb-3 flex items-center gap-2 rounded-xl border border-macaron-rose bg-macaron-rose/5 px-4 py-2.5 text-xs text-foreground/80">
                  <AlertTriangle className="size-3.5 shrink-0" style={{ color: 'var(--destructive)' }} />
                  {error}
                </div>
              )}

              {Object.entries(groups).map(([groupName, groupModels]) => {
                if (groupModels.length === 0) return null;
                return (
                  <div key={groupName} className="mb-3">
                    <p className="mb-2 text-[11px] font-medium text-muted-foreground">
                      {groupName}
                    </p>
                    <div className="flex flex-col gap-2">
                      {groupModels.map((m) => {
                        const isActive = m.name === activeModel || m.model_path === activeModel;
                        return (
                          <div
                            key={m.name}
                            className={cn(
                              'flex items-center justify-between rounded-xl border p-3 transition-colors',
                              isActive
                                ? 'border-primary bg-primary/5'
                                : 'border-border bg-card hover:border-primary/30'
                            )}
                          >
                            <div className="flex items-center gap-3">
                              <div
                                className={cn(
                                  'flex size-8 shrink-0 items-center justify-center rounded-lg',
                                  isActive ? 'bg-primary text-primary-foreground' : 'bg-secondary'
                                )}
                              >
                                <HardDrive className="size-4" />
                              </div>
                              <div>
                                <p className="text-sm font-medium text-foreground">{m.name}</p>
                                <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                                  {m.model_path}
                                </p>
                              </div>
                            </div>
                            {isActive ? (
                              <span className="inline-flex items-center gap-1 rounded-full bg-macaron-mint px-2.5 py-0.5 text-[10px] font-medium text-foreground/80">
                                <Check className="size-2.5" />
                                当前使用
                              </span>
                            ) : (
                              <button
                                type="button"
                                onClick={() => handleSwitch(m.name)}
                                disabled={switching}
                                className="btn btn-outline h-8 px-3 text-xs"
                              >
                                {switching ? <Loader2 className="size-3 animate-spin" /> : '切换'}
                              </button>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}

              {saved && (
                <div className="flex items-center justify-end gap-1 text-xs text-foreground">
                  <Check className="size-3.5" style={{ color: SUCCESS_COLOR }} />
                  模型已切换
                </div>
              )}

              <p className="mt-2 rounded-lg bg-background/40 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
                <span className="font-medium text-foreground">提示：</span>
                切换本地嵌入模型后已索引的文档不受影响，新上传的文档将使用新模型进行向量化。
              </p>
            </>
          )}
        </div>
      )}

      {/* API 模式：提示信息 */}
      {mode !== 'local' && (
        <div className="border-t border-border pt-4">
          <p className="rounded-lg bg-background/40 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
            <span className="font-medium text-foreground">提示：</span>
            API 模式下嵌入模型由上方配置决定，新上传的文档将使用配置的 API 模型进行向量化。
          </p>
        </div>
      )}
    </div>
  );
}

function KbStatusTab() {
  const { user } = useAuth();
  const companyId = user?.company_id ? String(user.company_id) : '';

  const [config, setConfig] = useState(null);
  const [graphStats, setGraphStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const loadData = async () => {
    setLoading(true);
    setError('');
    if (!companyId) {
      setConfig(null);
      setGraphStats(null);
      setError('当前账号未关联公司，无法加载 RAG 配置');
      setLoading(false);
      return;
    }
    try {
      const [configData, graphData] = await Promise.allSettled([
        getRagConfig(companyId),
        listGraphEntities(),
      ]);
      if (configData.status === 'fulfilled') setConfig(configData.value);
      if (graphData.status === 'fulfilled') setGraphStats(graphData.value);
    } catch (err) {
      setError('加载 RAG 配置失败');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadData(); }, [companyId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 py-12 text-xs text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        加载中...
      </div>
    );
  }

  const statusConfig = [
    { label: '嵌入模型',     value: config?.embedding_model || '—', sub: `${config?.embedding_model_count || 0} 个可用`, icon: Brain },
    { label: '检索策略',     value: 'BM25 + 向量 + RRF + Reranker', sub: config?.reranker_enabled ? '已启用 Cross-Encoder 精排' : '精排已关闭', icon: Search },
    { label: '知识图谱',     value: config?.graph_rag_enabled ? '已启用' : '已关闭', sub: graphStats ? `${graphStats.entity_count} 实体 · ${graphStats.relation_count} 关系` : '—', icon: Network },
    { label: '多模态检索',   value: config?.multimodal_enabled ? '已启用' : '未启用', sub: 'CLIP 以图搜图', icon: HardDrive },
    { label: '文档索引',     value: `${config?.document_count || 0} 个文档`, sub: config?.indexing_status || '未知', icon: Database },
    { label: '质量评估',     value: config?.evaluator_available ? '可用' : '不可用', sub: 'HitRate · MRR · NDCG', icon: Activity },
  ];

  return (
    <div className="flex flex-col gap-4">
      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-macaron-rose bg-macaron-rose/5 px-4 py-3 text-xs text-foreground/80">
          <AlertTriangle className="size-3.5 shrink-0" style={{ color: 'var(--destructive)' }} />
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {statusConfig.map((item) => (
          <div key={item.label} className="flex items-start gap-3 rounded-2xl border border-border bg-card p-3.5">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-secondary">
              <item.icon className="size-4 text-foreground/80" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-[11px] text-muted-foreground">{item.label}</p>
              <p className="mt-0.5 text-sm font-medium text-foreground">{item.value}</p>
              <p className="mt-0.5 text-[10px] text-muted-foreground">{item.sub}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-end">
        <button
          type="button"
          onClick={loadData}
          className="btn btn-outline h-8 px-3 text-xs"
        >
          <RefreshCw className="size-3.5" />
          刷新
        </button>
      </div>
    </div>
  );
}

export default function KnowledgeSection() {
  const [tab, setTab] = useState('docs');

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h2 className="font-heading text-2xl font-semibold tracking-tight text-foreground">
          知识库
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          管理 RAG 文档、选择嵌入模型、查看检索系统状态
        </p>
      </header>

      {/* Tab 切换器 */}
      <div className="inline-flex w-fit items-center gap-1 rounded-xl border border-border bg-card p-1">
        {KB_TABS.map(({ key, label, icon: Icon }) => {
          const isActive = tab === key;
          return (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              aria-pressed={isActive}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors',
                isActive
                  ? 'bg-primary text-primary-foreground shadow-sm'
                  : 'text-muted-foreground hover:bg-accent hover:text-foreground'
              )}
            >
              <Icon className="size-3.5" />
              {label}
            </button>
          );
        })}
      </div>

      {/* Tab 内容 */}
      <div>
        {tab === 'docs' && <KbDocsTab />}
        {tab === 'embedding' && <KbEmbeddingTab />}
        {tab === 'status' && <KbStatusTab />}
      </div>
    </div>
  );
}

