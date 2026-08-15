import client from './client';

/**
 * Fetch company LLM provider config in masked form.
 * The backend reads Company.llm_api_key (EncryptedText) and returns apiKeyMasked only.
 * The masked value is display-only and must not be written into password input value.
 * @param {number|string} companyId - Company ID
 * @returns {Promise<{providers: Object}>}
 */
export function getLlmConfig(companyId) {
  return client
    .get(`/admin/companies/${companyId}/llm-config`)
    .then((res) => res.data);
}

/**
 * Update company LLM provider config.
 * Empty apiKey means retain the existing server-side key; non-empty apiKey updates it.
 * Supports providerType/baseUrl/modelName/enabled/preferredTasks/apiKey/tpm/warnAt90.
 * This client does not store plaintext keys or perform real connection tests.
 * @param {number|string} companyId - Company ID
 * @param {Object} providers - { [providerKey]: { providerType, baseUrl, modelName, enabled, preferredTasks, apiKey, tpm, warnAt90 } }
 * @returns {Promise<{providers: Object}>}
 */
export function updateLlmConfig(companyId, providers) {
  return client
    .put(`/admin/companies/${companyId}/llm-config`, { providers })
    .then((res) => res.data);
}
