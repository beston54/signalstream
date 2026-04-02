/**
 * config.js — localStorage-based provider configuration.
 *
 * Structure:
 * { provider, claude_key, claude_model, openai_key, openai_endpoint, openai_model, ollama_model }
 */

const SignalConfig = {
    STORAGE_KEY: 'signalstream_config',

    _defaults: {
        provider: null,
        claude_key: '',
        claude_model: 'claude-sonnet-4-20250514',
        openai_key: '',
        openai_endpoint: 'https://api.openai.com/v1',
        openai_model: 'gpt-4o',
        ollama_model: '',
    },

    load() {
        try {
            const raw = localStorage.getItem(this.STORAGE_KEY);
            return raw ? { ...this._defaults, ...JSON.parse(raw) } : { ...this._defaults };
        } catch {
            return { ...this._defaults };
        }
    },

    save(config) {
        localStorage.setItem(this.STORAGE_KEY, JSON.stringify(config));
    },

    getActiveProvider() {
        return this.load().provider;
    },

    /**
     * Build X-LLM-* headers for the active provider.
     * @returns {Object} Headers dict, or empty object if no provider configured.
     */
    getLLMHeaders() {
        const config = this.load();
        if (!config.provider) return {};

        const headers = {
            'X-LLM-Provider': config.provider,
        };

        switch (config.provider) {
            case 'claude':
                headers['X-LLM-API-Key'] = config.claude_key;
                headers['X-LLM-Model'] = config.claude_model;
                break;
            case 'openai-compat':
                headers['X-LLM-API-Key'] = config.openai_key;
                headers['X-LLM-Model'] = config.openai_model;
                headers['X-LLM-Endpoint'] = config.openai_endpoint;
                break;
            case 'ollama':
                headers['X-LLM-Model'] = config.ollama_model;
                break;
        }

        return headers;
    },

    hasProvider() {
        const config = this.load();
        if (!config.provider) return false;
        if (config.provider === 'claude' && !config.claude_key) return false;
        if (config.provider === 'openai-compat' && !config.openai_key) return false;
        if (config.provider === 'ollama' && !config.ollama_model) return false;
        return true;
    },

    clear() {
        localStorage.removeItem(this.STORAGE_KEY);
    },
};
