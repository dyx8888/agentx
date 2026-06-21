import {
  DownloadOutlined,
  FileTextOutlined,
  PictureOutlined,
  VideoCameraOutlined,
  CodeOutlined,
  FilePdfOutlined,
  FileExcelOutlined,
  FilePptOutlined,
} from '@ant-design/icons';

const FILE_TYPE_ICONS = {
  pdf: <FilePdfOutlined />,
  excel: <FileExcelOutlined />,
  xlsx: <FileExcelOutlined />,
  ppt: <FilePptOutlined />,
  pptx: <FilePptOutlined />,
  image: <PictureOutlined />,
  video: <VideoCameraOutlined />,
  code: <CodeOutlined />,
  text: <FileTextOutlined />,
};

function getFileIcon(fileType) {
  return FILE_TYPE_ICONS[fileType?.toLowerCase()] || <FileTextOutlined />;
}

/**
 * 通用产出物卡片
 * 适用于文件、文档、报告等产出物
 */
export default function ArtifactCard({ data }) {
  return (
    <div className="mt-3 p-4 rounded-xl border border-[var(--color-hairline)] bg-white
      shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-lg bg-[var(--color-canvas-soft)]
          flex items-center justify-center text-lg text-[var(--color-link)] flex-shrink-0">
          {getFileIcon(data.file_type)}
        </div>
        <div className="flex-1 min-w-0">
          <h4 className="text-sm font-semibold text-[var(--color-ink)] mb-1 truncate">
            {data.title || '未命名文件'}
          </h4>
          <p className="text-xs text-[var(--color-mute)] mb-2 line-clamp-2">
            {data.summary || data.description || '暂无描述'}
          </p>
          <div className="flex items-center gap-2">
            <span className="px-2 py-0.5 text-[10px] font-medium rounded-full
              bg-[var(--color-link-bg-soft)] text-[var(--color-link)]">
              {data.type_label || data.file_type || '文件'}
            </span>
            {data.file_size && (
              <span className="text-[10px] text-[var(--color-mute)]">{data.file_size}</span>
            )}
          </div>
        </div>
        {data.download_url && (
          <a
            href={data.download_url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium
              text-[var(--color-link)] hover:text-white hover:bg-[var(--color-link)]
              border border-[var(--color-link)] rounded-lg
              transition-colors flex-shrink-0"
          >
            <DownloadOutlined />
            {data.download_label || '下载'}
          </a>
        )}
      </div>
    </div>
  );
}