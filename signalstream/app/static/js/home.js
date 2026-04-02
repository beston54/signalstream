/**
 * home.js — Home page: topic form submission, provider detection, first-run flow.
 */

document.addEventListener('DOMContentLoaded', () => {
    const topicForm = document.getElementById('topic-form');
    const topicInput = document.getElementById('topic-input');
    const providerSelector = document.getElementById('provider-selector');
    const noProviderHelp = document.getElementById('no-provider-help');
    const recentSection = document.getElementById('recent-analyses');
    const demoBtn = document.getElementById('demo-btn');

    let pendingTopic = null;

    // Load recent analyses
    loadRecentAnalyses();

    // Topic form submission
    topicForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        pendingTopic = topicInput.value.trim();
        if (!pendingTopic) return;

        if (SignalConfig.hasProvider()) {
            startAnalysis(pendingTopic);
        } else {
            // Show inline provider selector
            providerSelector.classList.remove('hidden');
            detectOllama();
        }
    });

    // Provider selection buttons
    document.querySelectorAll('.provider-select-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            selectProvider(btn.dataset.provider);
        });
    });

    // Demo data button
    if (demoBtn) {
        demoBtn.addEventListener('click', loadDemoData);
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
            } else {
                statusBadge.textContent = 'Not detected';
                statusBadge.className = 'badge badge-offline';
                noProviderHelp.classList.remove('hidden');
            }
        } catch {
            statusBadge.textContent = 'Not detected';
            statusBadge.className = 'badge badge-offline';
        }
    }

    function selectProvider(provider) {
        const config = SignalConfig.load();
        config.provider = provider;

        switch (provider) {
            case 'ollama':
                config.ollama_model = document.getElementById('ollama-model').value;
                break;
            case 'claude':
                config.claude_key = document.getElementById('claude-key').value;
                config.claude_model = document.getElementById('claude-model').value;
                break;
            case 'openai-compat':
                config.openai_endpoint = document.getElementById('openai-endpoint').value;
                config.openai_key = document.getElementById('openai-key').value;
                config.openai_model = document.getElementById('openai-model').value;
                break;
        }

        SignalConfig.save(config);

        if (pendingTopic) {
            startAnalysis(pendingTopic);
        }
    }

    async function startAnalysis(topic) {
        try {
            const resp = await SignalAPI.post('/api/jobs', { topic }, true);
            const data = await resp.json();

            if (resp.ok) {
                window.location.href = `/results/${data.job_id}`;
            } else {
                alert(data.message || 'Failed to start analysis');
            }
        } catch (err) {
            alert('Network error: ' + err.message);
        }
    }

    async function loadRecentAnalyses() {
        try {
            const resp = await SignalAPI.get('/api/jobs');
            const data = await resp.json();

            if (data.jobs && data.jobs.length > 0) {
                recentSection.classList.remove('hidden');
                const list = document.getElementById('job-list');
                list.innerHTML = data.jobs.slice(0, 5).map(job => `
                    <a href="/results/${job.job_id}" class="theme-card" style="display:block;text-decoration:none;color:inherit;">
                        <h4>${escapeHtml(job.topic || 'Untitled')}</h4>
                        <p class="theme-sentiment">${job.status} &mdash; ${job.created_at || ''}</p>
                    </a>
                `).join('');
            }
        } catch {
            // Silent fail — recent analyses are non-critical
        }
    }

    async function loadDemoData() {
        try {
            const resp = await SignalAPI.post('/api/jobs', { topic: '__demo__' }, false);
            const data = await resp.json();
            if (resp.ok) {
                window.location.href = `/results/${data.job_id}`;
            }
        } catch (err) {
            alert('Could not load demo data: ' + err.message);
        }
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
});
