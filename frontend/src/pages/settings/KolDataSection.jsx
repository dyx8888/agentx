import { useMemo, useState } from 'react';
import {
  AlertTriangle,
  Check,
  Database,
  FileSpreadsheet,
  Loader2,
  Search,
  Upload,
} from 'lucide-react';
import { importKols, searchKols } from '@/api/kol';

const REQUIRED_HEADERS = ['name', 'platform', 'category', 'data_source'];
const ALLOWED_SOURCES = ['manual_upload', 'public_web', 'cached_snapshot', 'official_api', 'partner_api'];
const SOURCE_LABELS = {
  manual_upload: '人工导入',
  public_web: '公开网页',
  cached_snapshot: '历史缓存',
  official_api: '官方 API',
  partner_api: '合作方 API',
};

const SAMPLE_ROWS = [
  'name,platform,platform_uid,followers,engagement_rate,category,sub_category,data_source,source_url,source_note,bio',
  '青竹公开网页达人,douyin,public-dy-001,980000,3.6,护肤,美白专场,public_web,https://public-source.invalid/kol,公开网页整理,适合护肤直播',
  '青竹人工导入达人,xiaohongshu,manual-xhs-001,126000,5.1,护肤,成分党,manual_upload,,运营人工整理,成分内容稳定',
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

function toNumber(value, fallback = 0) {
  if (value === undefined || value === null || value === '') return fallback;
  const parsed = Number(String(value).replace(/,/g, ''));
  return Number.isFinite(parsed) ? parsed : fallback;
}

function cleanText(value) {
  const text = String(value ?? '').trim();
  return text || undefined;
}

function normalizeItem(raw) {
  return {
    name: cleanText(raw.name),
    platform: cleanText(raw.platform),
    platform_uid: cleanText(raw.platform_uid),
    followers: toNumber(raw.followers),
    engagement_rate: toNumber(raw.engagement_rate),
    category: cleanText(raw.category) || '其他',
    sub_category: cleanText(raw.sub_category),
    avg_views: toNumber(raw.avg_views),
    avg_likes: toNumber(raw.avg_likes),
    avg_comments: toNumber(raw.avg_comments),
    avg_shares: toNumber(raw.avg_shares),
    price_range_low: raw.price_range_low === '' ? undefined : toNumber(raw.price_range_low, undefined),
    price_range_high: raw.price_range_high === '' ? undefined : toNumber(raw.price_range_high, undefined),
    location: cleanText(raw.location),
    verified: ['true', '1', 'yes', '是'].includes(String(raw.verified ?? '').trim().toLowerCase()),
    bio: cleanText(raw.bio),
    avatar_url: cleanText(raw.avatar_url),
    contact_info: cleanText(raw.contact_info),
    data_source: cleanText(raw.data_source) || 'manual_upload',
    source_url: cleanText(raw.source_url),
    source_note: cleanText(raw.source_note),
    is_active: raw.is_active === undefined
      ? true
      : !['false', '0', 'no', '否'].includes(String(raw.is_active).trim().toLowerCase()),
  };
}

function parseKolFileText(text, fileName) {
  if (fileName.toLowerCase().endsWith('.json')) {
    const parsed = JSON.parse(text);
    const rows = Array.isArray(parsed) ? parsed : parsed.items;
    if (!Array.isArray(rows)) throw new Error('JSON 需要是数组，或包含 items 数组');
    return rows.map(normalizeItem);
  }

  const rows = parseCsv(text);
  if (rows.length < 2) throw new Error('CSV 至少需要表头和 1 行数据');
  const headers = rows[0].map((h) => h.trim());
  const missing = REQUIRED_HEADERS.filter((h) => !headers.includes(h));
  if (missing.length > 0) throw new Error(`CSV 缺少必填列：${missing.join(', ')}`);

  return rows.slice(1).map((row) => {
    const raw = {};
    headers.forEach((header, idx) => {
      raw[header] = row[idx] ?? '';
    });
    return normalizeItem(raw);
  });
}

function validateItems(items) {
  const errors = [];
  items.forEach((item, index) => {
    const row = index + 1;
    if (!item.name) errors.push(`第 ${row} 行缺少 name`);
    if (!item.platform) errors.push(`第 ${row} 行缺少 platform`);
    if (!item.category) errors.push(`第 ${row} 行缺少 category`);
    if (!ALLOWED_SOURCES.includes(item.data_source)) {
      errors.push(`第 ${row} 行 data_source 不支持：${item.data_source}`);
    }
  });
  return errors;
}

function sourceLabel(source) {
  return SOURCE_LABELS[source] || source;
}

function DataSourceChips({ summary = {} }) {
  const entries = Object.entries(summary || {}).filter(([, count]) => Number(count) > 0);
  if (entries.length === 0) {
    return <span className="text-muted-foreground">暂无来源</span>;
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {entries.map(([source, count]) => (
        <span
          key={source}
          className="inline-flex items-center rounded-full bg-secondary px-2 py-0.5 text-[11px] text-muted-foreground"
        >
          {sourceLabel(source)} {count}
        </span>
      ))}
    </span>
  );
}

export default function KolDataSection() {
  const [items, setItems] = useState([]);
  const [fileName, setFileName] = useState('');
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const [searchResult, setSearchResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState('护肤');

  const sourceSummary = useMemo(() => {
    const summary = {};
    items.forEach((item) => {
      summary[item.data_source] = (summary[item.data_source] || 0) + 1;
    });
    return summary;
  }, [items]);

  const handleFile = async (file) => {
    if (!file) return;
    setError('');
    setResult(null);
    setSearchResult(null);
    try {
      const text = await file.text();
      const parsed = parseKolFileText(text, file.name);
      const validationErrors = validateItems(parsed);
      if (validationErrors.length) throw new Error(validationErrors.slice(0, 5).join('；'));
      setItems(parsed);
      setFileName(file.name);
    } catch (err) {
      setItems([]);
      setFileName('');
      setError(err.message || '解析文件失败');
    }
  };

  const submitImport = async (dryRun) => {
    if (items.length === 0) return;
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const data = await importKols(items, dryRun);
      setResult(data);
    } catch (err) {
      setError(err.response?.data?.detail || '导入失败');
    } finally {
      setLoading(false);
    }
  };

  const runSearch = async () => {
    setLoading(true);
    setError('');
    setSearchResult(null);
    try {
      const data = await searchKols({
        query,
        platform: 'all',
        category: '护肤',
        min_followers: 0,
        sort_by: 'followers',
        limit: 10,
      });
      setSearchResult(data);
    } catch (err) {
      setError(err.response?.data?.detail || '搜索失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <header>
        <h2 className="font-heading text-2xl font-semibold tracking-tight text-foreground">
          达人数据
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          没有企业 API 权限时，可导入人工整理、公开网页或历史缓存数据，并保留来源标识。
        </p>
      </header>

      <section className="rounded-2xl border border-border bg-card p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-foreground">导入文件</p>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              支持 CSV / JSON。必填列：name、platform、category、data_source。正式导入会拒绝 mock / demo / seed。
            </p>
          </div>
          <FileSpreadsheet className="size-5 shrink-0 text-muted-foreground" />
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-[1fr_auto]">
          <label className="flex cursor-pointer items-center justify-center gap-2 rounded-xl border border-dashed border-border bg-background/50 px-4 py-5 text-sm text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground">
            <Upload className="size-4" />
            <span>{fileName || '选择 CSV / JSON 文件'}</span>
            <input
              type="file"
              accept=".csv,.json,text/csv,application/json"
              className="hidden"
              onChange={(event) => handleFile(event.target.files?.[0])}
            />
          </label>
          <button
            type="button"
            className="btn btn-outline h-full px-4 text-xs"
            onClick={() => {
              const blob = new Blob([SAMPLE_ROWS], { type: 'text/csv;charset=utf-8' });
              const url = URL.createObjectURL(blob);
              const link = document.createElement('a');
              link.href = url;
              link.download = 'kol-import-template.csv';
              link.click();
              URL.revokeObjectURL(url);
            }}
          >
            下载模板
          </button>
        </div>
      </section>

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-macaron-rose bg-macaron-rose/5 px-4 py-3 text-xs text-foreground/80">
          <AlertTriangle className="size-3.5 shrink-0" style={{ color: 'var(--destructive)' }} />
          {error}
        </div>
      )}

      {items.length > 0 && (
        <section className="rounded-2xl border border-border bg-card p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-foreground">待导入预览</p>
              <div className="mt-1 flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
                <span>{items.length} 条达人 · 来源</span>
                <DataSourceChips summary={sourceSummary} />
              </div>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                className="btn btn-outline h-8 px-3 text-xs"
                disabled={loading}
                onClick={() => submitImport(true)}
              >
                {loading ? <Loader2 className="size-3 animate-spin" /> : <Check className="size-3" />}
                校验
              </button>
              <button
                type="button"
                className="btn btn-primary h-8 px-3 text-xs"
                disabled={loading}
                onClick={() => submitImport(false)}
              >
                {loading ? <Loader2 className="size-3 animate-spin" /> : <Database className="size-3" />}
                导入
              </button>
            </div>
          </div>

          <div className="mt-3 max-h-64 overflow-auto rounded-xl border border-border scrollbar-thin">
            <table className="w-full min-w-[720px] text-left text-xs">
              <thead className="bg-secondary text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">名称</th>
                  <th className="px-3 py-2 font-medium">平台</th>
                  <th className="px-3 py-2 font-medium">粉丝</th>
                  <th className="px-3 py-2 font-medium">互动率</th>
                  <th className="px-3 py-2 font-medium">分类</th>
                  <th className="px-3 py-2 font-medium">来源</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {items.slice(0, 20).map((item, idx) => (
                  <tr key={`${item.platform}-${item.platform_uid || item.name}-${idx}`}>
                    <td className="px-3 py-2 text-foreground">{item.name}</td>
                    <td className="px-3 py-2 text-muted-foreground">{item.platform}</td>
                    <td className="px-3 py-2 text-muted-foreground">{item.followers}</td>
                    <td className="px-3 py-2 text-muted-foreground">{item.engagement_rate}%</td>
                    <td className="px-3 py-2 text-muted-foreground">{item.category}</td>
                    <td className="px-3 py-2 text-muted-foreground">{sourceLabel(item.data_source)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {result && (
        <section className="rounded-2xl border border-macaron-mint bg-macaron-mint/10 p-4 text-sm">
          <div className="flex items-center gap-2 font-medium text-foreground">
            <Check className="size-4 text-macaron-mint" />
            {result.dry_run ? '校验通过' : '导入完成'}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
            <span>新增 {result.imported} · 更新 {result.updated} · 跳过 {result.skipped} · 来源</span>
            <DataSourceChips summary={result.data_source_summary} />
          </div>
          {result.data_source_warning && (
            <p className="mt-2 text-xs text-muted-foreground">{result.data_source_warning}</p>
          )}
        </section>
      )}

      <section className="rounded-2xl border border-border bg-card p-4">
        <div className="flex items-center gap-2">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="input-base h-9 flex-1 text-sm"
            placeholder="导入后搜索验证，例如：护肤"
          />
          <button
            type="button"
            className="btn btn-outline h-9 px-3 text-xs"
            disabled={loading || !query.trim()}
            onClick={runSearch}
          >
            {loading ? <Loader2 className="size-3.5 animate-spin" /> : <Search className="size-3.5" />}
            搜索验证
          </button>
        </div>

        {searchResult && (
          <div className="mt-3 rounded-xl border border-border bg-background/40 p-3">
            <p className="text-xs font-medium text-foreground">
              搜索结果 {searchResult.total} 条
            </p>
            <div className="mt-1 flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
              <span>来源</span>
              <DataSourceChips summary={searchResult.data_source_summary} />
            </div>
            {searchResult.data_source_warning && (
              <p className="mt-1 text-xs text-muted-foreground">{searchResult.data_source_warning}</p>
            )}
            <div className="mt-2 flex flex-col gap-2">
              {(searchResult.results || []).slice(0, 5).map((item) => (
                <div key={item.id} className="rounded-lg border border-border bg-card px-3 py-2">
                  <p className="text-sm font-medium text-foreground">{item.name}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {item.platform} · {item.followers} 粉丝 · {item.category} · {sourceLabel(item.data_source)}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

