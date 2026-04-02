/**
 * results.js — Results page: load data, render charts, manage states.
 *
 * States: loading (default), error, empty, populated.
 */

document.addEventListener('DOMContentLoaded', async () => {
    const jobId = document.querySelector('.results-page').dataset.jobId;

    const stateLoading = document.getElementById('state-loading');
    const stateError = document.getElementById('state-error');
    const stateEmpty = document.getElementById('state-empty');
    const statePopulated = document.getElementById('state-populated');

    function showState(state) {
        [stateLoading, stateError, stateEmpty, statePopulated].forEach(el => {
            el.classList.add('hidden');
        });
        state.classList.remove('hidden');
    }

    try {
        // Check if job is still running — poll if so
        const statusResp = await SignalAPI.get(`/api/jobs/${jobId}/status`);
        const statusData = await statusResp.json();

        if (statusResp.ok && ['pending', 'collecting', 'analyzing', 'theming', 'reporting'].includes(statusData.status)) {
            // Job still running — redirect to analyze page with polling
            window.location.href = `/analyze?job=${jobId}`;
            return;
        }

        if (statusResp.ok && statusData.status === 'failed') {
            showState(stateError);
            document.getElementById('error-message').textContent =
                statusData.error || 'Analysis failed. Please try again.';
            return;
        }

        // Load results
        const resultsResp = await SignalAPI.get(`/api/jobs/${jobId}/results`);

        if (!resultsResp.ok) {
            showState(stateError);
            const errData = await resultsResp.json();
            document.getElementById('error-message').textContent =
                errData.message || 'Could not load results.';
            return;
        }

        const results = await resultsResp.json();
        const stats = results.statistics;
        const job = results.job;

        if (!stats) {
            showState(stateEmpty);
            return;
        }

        // Populated state
        showState(statePopulated);

        // Metrics
        document.getElementById('metric-posts').textContent = stats.total_posts || '--';
        document.getElementById('metric-sentiment').textContent =
            capitalize(stats.dominant_sentiment || '--');
        document.getElementById('metric-emotion').textContent =
            capitalize(stats.dominant_emotion || '--');
        document.getElementById('metric-cost').textContent =
            stats.estimated_cost ? `~$${stats.estimated_cost.toFixed(2)}` : '--';

        // Charts
        if (stats.sentiment_counts) {
            SignalCharts.renderSentiment('sentiment-chart', stats.sentiment_counts);
        }
        if (stats.emotion_counts) {
            SignalCharts.renderEmotions('emotion-chart', stats.emotion_counts);
        }
        if (stats.themes) {
            SignalCharts.renderThemes('theme-chart', stats.themes);
            renderThemeCards(stats.themes);
        }
        if (stats.community_counts) {
            SignalCharts.renderCommunities('community-chart', stats.community_counts);
        }

        // Export links
        document.getElementById('export-json-btn').href = `/api/jobs/${jobId}/export/json`;
        document.getElementById('export-pdf-btn').href = `/api/jobs/${jobId}/export/pdf`;

    } catch (err) {
        showState(stateError);
        document.getElementById('error-message').textContent =
            'Network error: ' + err.message;
    }

    function renderThemeCards(themes) {
        const container = document.getElementById('themes-list');
        container.innerHTML = themes.map(theme => `
            <div class="theme-card">
                <h4>${escapeHtml(theme.name)} <span class="theme-percentage">${theme.percentage}%</span></h4>
                <p class="theme-sentiment">Sentiment: ${theme.sentiment_skew} | ${theme.post_count} posts</p>
                <p>${escapeHtml(theme.description)}</p>
                ${theme.representative_quotes ? theme.representative_quotes.map(q =>
                    `<blockquote>${escapeHtml(q)}</blockquote>`
                ).join('') : ''}
            </div>
        `).join('');
    }

    function capitalize(str) {
        return str.charAt(0).toUpperCase() + str.slice(1);
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
});
