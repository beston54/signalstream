/**
 * polling.js — Poll job status with adaptive intervals.
 *
 * Interval: 2s initially, doubles to 4s after 60s, 8s after 5min.
 */

class JobPoller {
    constructor(jobId, onUpdate, onComplete, onError) {
        this.jobId = jobId;
        this.onUpdate = onUpdate;
        this.onComplete = onComplete;
        this.onError = onError;
        this.timer = null;
        this.startTime = Date.now();
        this.stopped = false;
    }

    _getInterval() {
        const elapsed = (Date.now() - this.startTime) / 1000;
        if (elapsed > 300) return 8000;  // After 5 min
        if (elapsed > 60) return 4000;   // After 1 min
        return 2000;                      // Default
    }

    start() {
        this.stopped = false;
        this._poll();
    }

    stop() {
        this.stopped = true;
        if (this.timer) {
            clearTimeout(this.timer);
            this.timer = null;
        }
    }

    async _poll() {
        if (this.stopped) return;

        try {
            const resp = await SignalAPI.get(`/api/jobs/${this.jobId}/status`);
            const data = await resp.json();

            if (!resp.ok) {
                this.onError(data);
                this.stop();
                return;
            }

            this.onUpdate(data);

            if (data.status === 'completed') {
                this.onComplete(data);
                this.stop();
                return;
            }

            if (data.status === 'failed') {
                this.onError(data);
                this.stop();
                return;
            }

            // Schedule next poll
            this.timer = setTimeout(() => this._poll(), this._getInterval());
        } catch (err) {
            this.onError({ message: 'Network error: ' + err.message });
            // Retry on network errors
            this.timer = setTimeout(() => this._poll(), this._getInterval());
        }
    }
}
