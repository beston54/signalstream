/**
 * api.js — Shared fetch wrapper with CSRF token and LLM headers.
 */

const SignalAPI = {
    /**
     * Get the CSRF token from the cookie.
     */
    getCSRFToken() {
        const match = document.cookie.match(/csrf_token=([^;]+)/);
        return match ? match[1] : '';
    },

    /**
     * Make an API request with proper headers.
     * @param {string} url - The URL to fetch.
     * @param {Object} options - Fetch options (method, body, etc.).
     * @param {boolean} includeLLM - Whether to include X-LLM-* headers.
     * @returns {Promise<Response>}
     */
    async request(url, options = {}, includeLLM = false) {
        const headers = {
            'Content-Type': 'application/json',
            'X-CSRF-Token': this.getCSRFToken(),
            ...(options.headers || {}),
        };

        if (includeLLM) {
            Object.assign(headers, SignalConfig.getLLMHeaders());
        }

        const response = await fetch(url, {
            ...options,
            headers,
        });

        return response;
    },

    async get(url) {
        return this.request(url, { method: 'GET' });
    },

    async post(url, body, includeLLM = false) {
        return this.request(url, {
            method: 'POST',
            body: JSON.stringify(body),
        }, includeLLM);
    },

    async delete(url) {
        return this.request(url, { method: 'DELETE' });
    },
};
