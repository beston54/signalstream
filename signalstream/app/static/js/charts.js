/**
 * charts.js — Chart.js rendering for dashboard results.
 *
 * All charts render from JSON API data. No server round-trips for chart rendering.
 */

const SignalCharts = {
    _chartInstances: {},

    /**
     * Render the sentiment breakdown as a doughnut chart.
     */
    renderSentiment(canvasId, sentimentCounts) {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return;

        const labels = Object.keys(sentimentCounts);
        const data = Object.values(sentimentCounts);
        const colors = {
            positive: '#16a34a',
            negative: '#dc2626',
            neutral: '#6c757d',
            mixed: '#d97706',
        };

        this._destroy(canvasId);
        this._chartInstances[canvasId] = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: labels.map(l => l.charAt(0).toUpperCase() + l.slice(1)),
                datasets: [{
                    data,
                    backgroundColor: labels.map(l => colors[l] || '#6c757d'),
                }],
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { position: 'bottom' },
                },
            },
        });
    },

    /**
     * Render emotion distribution as a horizontal bar chart.
     */
    renderEmotions(canvasId, emotionCounts) {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return;

        const sorted = Object.entries(emotionCounts).sort((a, b) => b[1] - a[1]);

        this._destroy(canvasId);
        this._chartInstances[canvasId] = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: sorted.map(([e]) => e.charAt(0).toUpperCase() + e.slice(1)),
                datasets: [{
                    data: sorted.map(([, c]) => c),
                    backgroundColor: '#2563eb',
                }],
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                plugins: { legend: { display: false } },
                scales: { x: { beginAtZero: true, ticks: { stepSize: 1 } } },
            },
        });
    },

    /**
     * Render theme frequency as a bar chart.
     */
    renderThemes(canvasId, themes) {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return;

        this._destroy(canvasId);
        this._chartInstances[canvasId] = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: themes.map(t => t.name),
                datasets: [{
                    data: themes.map(t => t.percentage),
                    backgroundColor: '#2563eb',
                }],
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true, max: 100, ticks: { callback: v => v + '%' } } },
            },
        });
    },

    /**
     * Render community breakdown as a pie chart.
     */
    renderCommunities(canvasId, communityCounts) {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return;

        const labels = Object.keys(communityCounts);
        const data = Object.values(communityCounts);

        this._destroy(canvasId);
        this._chartInstances[canvasId] = new Chart(ctx, {
            type: 'pie',
            data: {
                labels,
                datasets: [{
                    data,
                    backgroundColor: [
                        '#2563eb', '#16a34a', '#d97706', '#dc2626',
                        '#7c3aed', '#0891b2', '#c026d3', '#65a30d',
                    ],
                }],
            },
            options: {
                responsive: true,
                plugins: { legend: { position: 'bottom' } },
            },
        });
    },

    _destroy(canvasId) {
        if (this._chartInstances[canvasId]) {
            this._chartInstances[canvasId].destroy();
            delete this._chartInstances[canvasId];
        }
    },
};
