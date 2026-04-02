/**
 * settings.js — Settings page: provider configuration and data management.
 */

document.addEventListener('DOMContentLoaded', () => {
    const deleteBtn = document.getElementById('delete-all-btn');

    // Load saved config into form fields
    const config = SignalConfig.load();

    if (config.claude_key) document.getElementById('claude-key').value = config.claude_key;
    if (config.claude_model) document.getElementById('claude-model').value = config.claude_model;
    if (config.openai_endpoint) document.getElementById('openai-endpoint').value = config.openai_endpoint;
    if (config.openai_key) document.getElementById('openai-key').value = config.openai_key;
    if (config.openai_model) document.getElementById('openai-model').value = config.openai_model;

    // Highlight active provider card
    if (config.provider) {
        const activeCard = document.querySelector(`.provider-card[data-provider="${config.provider}"]`);
        if (activeCard) activeCard.classList.add('active');
    }

    // Detect Ollama
    detectOllama();

    // Provider selection
    document.querySelectorAll('.provider-select-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const provider = btn.dataset.provider;
            const newConfig = SignalConfig.load();
            newConfig.provider = provider;

            switch (provider) {
                case 'ollama':
                    newConfig.ollama_model = document.getElementById('ollama-model').value;
                    break;
                case 'claude':
                    newConfig.claude_key = document.getElementById('claude-key').value;
                    newConfig.claude_model = document.getElementById('claude-model').value;
                    break;
                case 'openai-compat':
                    newConfig.openai_endpoint = document.getElementById('openai-endpoint').value;
                    newConfig.openai_key = document.getElementById('openai-key').value;
                    newConfig.openai_model = document.getElementById('openai-model').value;
                    break;
            }

            // Validate
            btn.textContent = 'Validating...';
            btn.disabled = true;

            try {
                const headers = {};
                headers['X-LLM-Provider'] = provider;
                if (provider === 'claude') {
                    headers['X-LLM-API-Key'] = newConfig.claude_key;
                    headers['X-LLM-Model'] = newConfig.claude_model;
                } else if (provider === 'openai-compat') {
                    headers['X-LLM-API-Key'] = newConfig.openai_key;
                    headers['X-LLM-Model'] = newConfig.openai_model;
                    headers['X-LLM-Endpoint'] = newConfig.openai_endpoint;
                } else if (provider === 'ollama') {
                    headers['X-LLM-Model'] = newConfig.ollama_model;
                }

                const resp = await SignalAPI.request('/api/providers/validate', {
                    method: 'POST',
                    headers,
                });

                const data = await resp.json();

                if (data.valid) {
                    SignalConfig.save(newConfig);
                    // Update active state
                    document.querySelectorAll('.provider-card').forEach(c => c.classList.remove('active'));
                    btn.closest('.provider-card').classList.add('active');
                    btn.textContent = 'Connected!';
                    setTimeout(() => { btn.textContent = `Use ${provider === 'openai-compat' ? 'This Provider' : provider.charAt(0).toUpperCase() + provider.slice(1)}`; }, 2000);
                } else {
                    alert(data.message || 'Validation failed');
                    btn.textContent = 'Try Again';
                }
            } catch (err) {
                alert('Connection error: ' + err.message);
                btn.textContent = 'Try Again';
            } finally {
                btn.disabled = false;
            }
        });
    });

    // Delete all data
    if (deleteBtn) {
        deleteBtn.addEventListener('click', async () => {
            if (!confirm('This will permanently delete all analysis data. Continue?')) return;

            try {
                await SignalAPI.delete('/api/data');
                alert('All data deleted.');
            } catch (err) {
                alert('Error: ' + err.message);
            }
        });
    }

    async function detectOllama() {
        const statusBadge = document.getElementById('ollama-status');
        const modelSelect = document.getElementById('ollama-model');

        try {
            const resp = await SignalAPI.get('/api/providers/detect');
            const data = await resp.json();

            if (data.ollama && data.ollama.models && data.ollama.models.length > 0) {
                statusBadge.textContent = 'Online';
                statusBadge.className = 'badge badge-online';
                modelSelect.innerHTML = '';
                data.ollama.models.forEach(model => {
                    const opt = document.createElement('option');
                    opt.value = model;
                    opt.textContent = model;
                    modelSelect.appendChild(opt);
                });
                // Restore saved selection
                if (config.ollama_model) modelSelect.value = config.ollama_model;
            } else {
                statusBadge.textContent = 'Not detected';
                statusBadge.className = 'badge badge-offline';
            }
        } catch {
            statusBadge.textContent = 'Not detected';
            statusBadge.className = 'badge badge-offline';
        }
    }
});
