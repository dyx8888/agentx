import { useState } from 'react';
import { CheckOutlined, CloseOutlined, ExclamationCircleOutlined } from '@ant-design/icons';
import { Modal, Input, message } from 'antd';

const { TextArea } = Input;

/**
 * 审核操作组件
 * 为每个产出物卡片提供"通过/驳回"操作按钮
 */
export default function ReviewActions({ reviewStatus, onApprove, onReject, disabled }) {
  const [isRejecting, setIsRejecting] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleApprove = async () => {
    setIsSubmitting(true);
    try {
      await onApprove?.();
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRejectClick = () => {
    setRejectReason('');
    setIsRejecting(true);
  };

  const handleRejectConfirm = async () => {
    if (!rejectReason.trim()) {
      message.warning('请输入驳回理由');
      return;
    }
    setIsSubmitting(true);
    try {
      await onReject?.(rejectReason.trim());
      setIsRejecting(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRejectCancel = () => {
    setIsRejecting(false);
    setRejectReason('');
  };

  // 已审核状态展示
  if (reviewStatus === 'approved') {
    return (
      <div className="flex items-center gap-2 mt-3 pt-3 border-t border-[var(--color-border)]">
        <span className="flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium
          bg-[var(--color-success-light)] text-[var(--color-success)]">
          <CheckOutlined />
          已通过
        </span>
      </div>
    );
  }

  if (reviewStatus === 'rejected') {
    return (
      <div className="mt-3 pt-3 border-t border-[var(--color-border)]">
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium
            bg-[var(--color-error-light)] text-[var(--color-error)]">
            <CloseOutlined />
            已驳回
          </span>
          {rejectReason && (
            <span className="text-xs text-[var(--color-text-tertiary)] truncate max-w-[200px]">
              {rejectReason}
            </span>
          )}
        </div>
      </div>
    );
  }

  // 待审核操作按钮
  return (
    <>
      <div className="flex items-center gap-2 mt-3 pt-3 border-t border-[var(--color-border)]">
        <button
          onClick={handleApprove}
          disabled={disabled || isSubmitting}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium
            text-[var(--color-success)] border border-[var(--color-success)]
            rounded-lg hover:bg-[var(--color-success-light)]
            disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <CheckOutlined />
          通过
        </button>
        <button
          onClick={handleRejectClick}
          disabled={disabled || isSubmitting}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium
            text-[var(--color-error)] border border-[var(--color-error)]
            rounded-lg hover:bg-[var(--color-error-light)]
            disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <CloseOutlined />
          驳回
        </button>
      </div>

      {/* 驳回理由弹窗 */}
      <Modal
        title={
          <div className="flex items-center gap-2">
            <ExclamationCircleOutlined className="text-[var(--color-warning)]" />
            <span>驳回理由</span>
          </div>
        }
        open={isRejecting}
        onOk={handleRejectConfirm}
        onCancel={handleRejectCancel}
        confirmLoading={isSubmitting}
        okText="确认驳回"
        cancelText="取消"
        okButtonProps={{ danger: true }}
        centered
        width={440}
      >
        <p className="text-sm text-[var(--color-text-secondary)] mb-3">
          请输入驳回原因，以便后续修正：
        </p>
        <TextArea
          value={rejectReason}
          onChange={(e) => setRejectReason(e.target.value)}
          placeholder="例如：数据不够准确，请重新分析..."
          rows={4}
          maxLength={500}
          showCount
          autoFocus
        />
      </Modal>
    </>
  );
}