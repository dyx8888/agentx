import client from './client';

export function listConversationTasks(conversationId) {
  return client.get(`/chat/conversations/${conversationId}/tasks`).then((res) => res.data);
}

export function resumeConversationTask(conversationId, taskId) {
  return client.post(`/chat/conversations/${conversationId}/tasks/${taskId}/resume`).then((res) => res.data);
}
