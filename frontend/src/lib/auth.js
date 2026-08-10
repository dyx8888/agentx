import client from '@/api/client';

/**
 * 修改当前用户密码
 * 复用 @/api/client 的 axios 实例（自动携带 JWT + 401 静默刷新）
 * @param {string} currentPassword - 当前密码
 * @param {string} newPassword - 新密码（≥8 位）
 * @returns {Promise<{success: boolean, message: string}>}
 */
export function changePassword(currentPassword, newPassword) {
  return client
    .post('/auth/password/change', {
      current_password: currentPassword,
      new_password: newPassword,
    })
    .then((res) => res.data);
}
