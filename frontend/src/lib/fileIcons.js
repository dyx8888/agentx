import {
  FileText,
  FileSpreadsheet,
  Image as ImageIcon,
  File,
} from 'lucide-react';

/* ═══════════════════════════════════════════════════════════════
   文件类型 → 图标映射（共享）
   doc→blue | sheet→mint | image→pink | pdf→yellow
   使用方：FilePanel / FilePreviewModal / MessageBubble
   ═══════════════════════════════════════════════════════════════ */
export const FILE_ICON_MAP = {
  doc:    { Icon: FileText,        tint: 'bg-macaron-blue'   },
  sheet:  { Icon: FileSpreadsheet, tint: 'bg-macaron-mint'   },
  image:  { Icon: ImageIcon,       tint: 'bg-macaron-pink'   },
  pdf:    { Icon: File,            tint: 'bg-macaron-yellow' },
  text:   { Icon: FileText,        tint: 'bg-macaron-blue'   },
  report: { Icon: FileText,        tint: 'bg-macaron-mint'   },
  data:   { Icon: FileSpreadsheet, tint: 'bg-macaron-pink'   },
};
