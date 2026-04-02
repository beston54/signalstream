/**
 * analyze.js — Analysis page: poll job progress and redirect on completion.
 */

document.addEventListener('DOMContentLoaded', () => {
    // Job ID is passed via URL query param: /analyze?job=<id>
    const params = new URLSearchParams(window.location.search);
    const jobId = params.get('job');

    if (!jobId) {
        window.location.href = '/';
        return;
    }

    const progressBar = document.getElementById('progress-bar');
    const progressStage = document.getElementById('progress-stage');
    const progressItems = document.getElementById('progress-items');
    const progressTotal = document.getElementById('progress-total');
    const progressMessage = document.getElementById('progress-message');
    const progressElapsed = document.getElementById('progress-elapsed');
    const cancelBtn = document.getElementById('cancel-btn');
    const errorContainer = document.getElementById('error-container');

    const stageLabels = {
        pending: 'Preparing...',
        collecting: 'Collecting posts...',
        analyzing: 'Analyzing sentiment...',
        theming: 'Extracting themes...',
        reporting: 'Generating report...',
        completed: 'Analysis complete!',
        failed: 'Analysis failed',
    };

    const poller = new JobPoller(
        jobId,
        // onUpdate
        (data) => {
            progressStage.textContent = stageLabels[data.stage] || data.stage;
            progressItems.textContent = data.items_completed;
            progressTotal.textContent = data.items_total;
            progressMessage.textContent = data.message || '';

            const pct = data.items_total > 0
                ? Math.round((data.items_completed / data.items_total) * 100)
                : 0;
            progressBar.style.width = pct + '%';

            const elapsed = Math.round(data.elapsed_seconds);
            const mins = Math.floor(elapsed / 60);
            const secs = elapsed % 60;
            progressElapsed.textContent = mins > 0
                ? `${mins}m ${secs}s elapsed`
                : `${secs}s elapsed`;
        },
        // onComplete
        (data) => {
            window.location.href = `/results/${jobId}`;
        },
        // onError
        (data) => {
            document.getElementById('progress-container').classList.add('hidden');
            errorContainer.classList.remove('hidden');
            document.getElementById('error-message').textContent =
                data.error || data.message || 'An unknown error occurred.';
        }
    );

    poller.start();

    // Cancel button
    cancelBtn.addEventListener('click', async () => {
        cancelBtn.disabled = true;
        cancelBtn.textContent = 'Cancelling...';

        try {
            await SignalAPI.post(`/api/jobs/${jobId}/cancel`, {}, true);
            window.location.href = '/';
        } catch {
            cancelBtn.disabled = false;
            cancelBtn.textContent = 'Cancel';
        }
    });
});
