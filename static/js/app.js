/**
 * Signalstream — Status page polling with pipeline stages, preview and email gate.
 * Fetches /api/status/<job_id> every 3 seconds and updates the DOM.
 */
(function () {
    "use strict";

    const page = document.querySelector(".status-page");
    if (!page) return;

    const jobId = page.dataset.jobId;
    if (!jobId) return;

    const $phase      = document.getElementById("phase");
    const $badge      = document.getElementById("badge");
    const $bar        = document.getElementById("progress-bar");
    const $pct        = document.getElementById("pct");
    const $message    = document.getElementById("message");
    const $actions    = document.getElementById("actions");
    const $errorBox   = document.getElementById("error-box");
    const $errorText  = document.getElementById("error-text");
    const $preview    = document.getElementById("preview-section");
    const $emailGate  = document.getElementById("email-gate");

    // Pipeline stage elements
    const stages = {
        collecting: { el: document.getElementById("stage-collect"), conn: null },
        analyzing:  { el: document.getElementById("stage-analyze"), conn: document.getElementById("conn-1") },
        theming:    { el: document.getElementById("stage-theme"),   conn: document.getElementById("conn-2") },
        generating: { el: document.getElementById("stage-report"),  conn: document.getElementById("conn-3") },
    };
    const stageOrder = ["collecting", "analyzing", "theming", "generating"];

    // Emotion color map (Signalstream palette)
    const EMOTION_COLORS = {
        enthusiastic: "#34D399",
        hopeful: "#4DA8FF",
        curious: "#818CF8",
        satisfied: "#38BDF8",
        amused: "#A78BFA",
        neutral: "#8899B0",
        skeptical: "#F2CC8F",
        concerned: "#FFB547",
        frustrated: "#FF7B8E",
        angry: "#EF4444",
    };

    let polling = true;
    let emailSubmitted = false;
    let consecutivePollFailures = 0;

    // Duration hint element (hidden on terminal states)
    const $durationHint = document.getElementById("duration-hint");

    // Reconnection banner element
    const $reconnectBanner = document.getElementById("reconnect-banner");

    // Read CSRF token from meta tag for state-mutating requests
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    const csrfToken = csrfMeta ? csrfMeta.getAttribute("content") : "";

    // Cancel button
    const $cancelSection = document.getElementById("cancel-section");
    const $cancelBtn = document.getElementById("cancel-btn");
    if ($cancelBtn) {
        $cancelBtn.addEventListener("click", function () {
            $cancelBtn.disabled = true;
            $cancelBtn.textContent = "Cancelling...";
            fetch("/api/jobs/" + jobId + "/cancel", { method: "POST", headers: { "X-CSRFToken": csrfToken } })
                .then(function (resp) { return resp.json(); })
                .then(function (data) {
                    if (!data.ok) {
                        $cancelBtn.disabled = false;
                        $cancelBtn.textContent = "Cancel Analysis";
                    }
                })
                .catch(function () {
                    $cancelBtn.disabled = false;
                    $cancelBtn.textContent = "Cancel Analysis";
                });
        });
    }

    function hideCancelButton() {
        if ($cancelSection) $cancelSection.style.display = "none";
    }

    function updatePipelineStages(status) {
        const activeIdx = stageOrder.indexOf(status);
        stageOrder.forEach(function (key, i) {
            const s = stages[key];
            if (!s || !s.el) return;
            s.el.classList.remove("active", "done");
            if (s.conn) s.conn.classList.remove("done");

            if (status === "complete") {
                s.el.classList.add("done");
                if (s.conn) s.conn.classList.add("done");
            } else if (i < activeIdx) {
                s.el.classList.add("done");
                if (s.conn) s.conn.classList.add("done");
            } else if (i === activeIdx) {
                s.el.classList.add("active");
            }
        });
    }

    function renderPreview(preview) {
        if (!preview || !$preview) return;

        const $posts = document.getElementById("preview-posts");
        const $communities = document.getElementById("preview-communities");
        const $emotion = document.getElementById("preview-emotion");
        const $emotions = document.getElementById("preview-emotions");
        const $themes = document.getElementById("preview-themes");

        if ($posts) $posts.textContent = preview.total_posts || "--";
        if ($communities) $communities.textContent = preview.communities_scanned || "--";
        if ($emotion) $emotion.textContent = (preview.dominant_emotion || "--").charAt(0).toUpperCase() + (preview.dominant_emotion || "").slice(1);

        if ($emotions && preview.top_emotions && preview.top_emotions.length > 0) {
            $emotions.textContent = "";
            preview.top_emotions.forEach(function (e) {
                const color = EMOTION_COLORS[e.emotion] || "#8899B0";

                const row = document.createElement("div");
                row.className = "preview-emotion-row";

                const label = document.createElement("span");
                label.className = "preview-emotion-label";
                label.style.color = color;
                label.textContent = e.emotion.charAt(0).toUpperCase() + e.emotion.slice(1);

                const track = document.createElement("div");
                track.className = "preview-emotion-track";
                const bar = document.createElement("div");
                bar.className = "preview-emotion-bar";
                bar.style.width = e.pct + "%";
                bar.style.background = color;
                track.appendChild(bar);

                const pct = document.createElement("span");
                pct.className = "preview-emotion-pct";
                pct.textContent = e.pct + "%";

                row.appendChild(label);
                row.appendChild(track);
                row.appendChild(pct);
                $emotions.appendChild(row);
            });
        }

        if ($themes && preview.top_themes && preview.top_themes.length > 0) {
            $themes.textContent = "";
            const heading = document.createElement("h4");
            heading.textContent = "Top Themes";
            $themes.appendChild(heading);
            preview.top_themes.forEach(function (t) {
                const chip = document.createElement("span");
                chip.className = "preview-theme-chip";
                chip.textContent = t;
                $themes.appendChild(chip);
            });
        }

        $preview.style.display = "block";
    }

    function showEmailGate() {
        if (!$emailGate) return;
        $emailGate.style.display = "block";

        const $input = document.getElementById("email-input");
        const $submit = document.getElementById("email-submit");
        const $error = document.getElementById("email-error");
        const $consent = document.getElementById("email-consent");
        const $consentError = document.getElementById("consent-error");

        if ($submit && !$submit._bound) {
            $submit._bound = true;
            $submit.addEventListener("click", function () {
                const email = ($input ? $input.value : "").trim();
                if (!email || email.indexOf("@") < 1) {
                    if ($error) { $error.textContent = "Please enter a valid email address."; $error.style.display = "block"; }
                    return;
                }
                if ($consent && !$consent.checked) {
                    if ($consentError) $consentError.style.display = "block";
                    return;
                }
                if ($error) $error.style.display = "none";
                if ($consentError) $consentError.style.display = "none";
                $submit.disabled = true;
                $submit.textContent = "Submitting...";

                fetch("/api/submit-email/" + jobId, {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
                    body: JSON.stringify({ email: email, consent: true }),
                })
                .then(function (resp) { return resp.json(); })
                .then(function (data) {
                    if (data.ok) {
                        emailSubmitted = true;
                        $emailGate.style.display = "none";
                        if ($actions) $actions.style.display = "flex";
                    } else {
                        if ($error) { $error.textContent = data.error || "Submission failed."; $error.style.display = "block"; }
                        $submit.disabled = false;
                        $submit.textContent = "Get Report";
                    }
                })
                .catch(function () {
                    if ($error) { $error.textContent = "Network error. Please try again."; $error.style.display = "block"; }
                    $submit.disabled = false;
                    $submit.textContent = "Get Report";
                });
            });
        }
    }

    function fetchTrends(jobId) {
        fetch("/api/trends/" + jobId)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.deltas && Object.keys(data.deltas).length > 0) {
                    var section = document.getElementById("trend-section");
                    var deltasDiv = document.getElementById("trend-deltas");
                    if (!section || !deltasDiv) return;

                    var d = data.deltas;
                    var items = [
                        { label: "Positive", delta: d.positive_delta, color: "#5DD9A5" },
                        { label: "Negative", delta: d.negative_delta, color: "#FF7B8E" },
                        { label: "Neutral", delta: d.neutral_delta, color: "#8899B0" },
                    ];

                    deltasDiv.innerHTML = items.map(function (item) {
                        var arrow = item.delta > 0 ? "\u2191" : item.delta < 0 ? "\u2193" : "\u2192";
                        var sign = item.delta > 0 ? "+" : "";
                        return '<div style="background: #161E2E; border-radius: 8px; padding: 0.75rem 1rem; min-width: 120px;">'
                            + '<div style="font-size: 1.2rem; color: ' + item.color + ';">' + arrow + ' ' + sign + item.delta + '%</div>'
                            + '<div style="font-size: 0.75rem; color: #8899B0;">' + item.label + '</div>'
                            + '</div>';
                    }).join("");

                    if (data.deltas.posts_delta !== undefined) {
                        var pd = data.deltas.posts_delta;
                        var pArrow = pd > 0 ? "\u2191" : pd < 0 ? "\u2193" : "\u2192";
                        var pSign = pd > 0 ? "+" : "";
                        deltasDiv.innerHTML += '<div style="background: #161E2E; border-radius: 8px; padding: 0.75rem 1rem; min-width: 120px;">'
                            + '<div style="font-size: 1.2rem; color: #4DA8FF;">' + pArrow + ' ' + pSign + pd + '</div>'
                            + '<div style="font-size: 0.75rem; color: #8899B0;">Posts</div>'
                            + '</div>';
                    }

                    section.style.display = "block";
                }
            })
            .catch(function () {});
    }

    async function poll() {
        if (!polling) return;

        try {
            const resp = await fetch(`/api/status/${jobId}`);
            if (!resp.ok) {
                consecutivePollFailures++;
                if (consecutivePollFailures >= 2 && $reconnectBanner) {
                    $reconnectBanner.style.display = "block";
                }
                schedule();
                return;
            }

            const data = await resp.json();

            // Successful poll — reset failure counter and hide reconnect banner
            consecutivePollFailures = 0;
            if ($reconnectBanner) $reconnectBanner.style.display = "none";

            if ($phase)   $phase.textContent = data.phase || "";
            if ($badge)   { $badge.textContent = data.status; $badge.dataset.status = data.status; }
            if ($bar)     $bar.style.width = (data.progress_pct || 0) + "%";
            if ($pct)     $pct.textContent = data.progress_pct || 0;
            if ($message) $message.textContent = data.message || "";

            updatePipelineStages(data.status);

            if (data.status === "complete") {
                polling = false;
                hideCancelButton();
                if ($durationHint) $durationHint.style.display = "none";
                if ($errorBox) $errorBox.style.display = "none";

                if (data.preview) {
                    renderPreview(data.preview);
                }

                fetchTrends(jobId);

                if (!data.email_gate_enabled || data.email_submitted) {
                    // Email gate disabled in server config or already submitted
                    emailSubmitted = true;
                    if ($actions) $actions.style.display = "flex";
                    if ($emailGate) $emailGate.style.display = "none";
                } else {
                    showEmailGate();
                }

                const dlBtn = document.getElementById("download-btn");
                if (dlBtn) dlBtn.href = `/download/${jobId}`;
                return;
            }

            if (data.status === "cancelled") {
                polling = false;
                hideCancelButton();
                if ($durationHint) $durationHint.style.display = "none";
                if ($actions) $actions.style.display = "none";
                if ($errorBox) $errorBox.style.display = "block";
                if ($errorText) $errorText.textContent = data.message || "Job was cancelled.";
                return;
            }

            if (data.status === "error") {
                polling = false;
                hideCancelButton();
                if ($durationHint) $durationHint.style.display = "none";
                if ($actions) $actions.style.display = "none";
                if ($errorBox) $errorBox.style.display = "block";
                if ($errorText) $errorText.textContent = data.message || "An error occurred.";
                return;
            }

        } catch (err) {
            console.warn("Polling error:", err);
            consecutivePollFailures++;
            if (consecutivePollFailures >= 2 && $reconnectBanner) {
                $reconnectBanner.style.display = "block";
            }
        }

        schedule();
    }

    function schedule() {
        setTimeout(poll, 3000);
    }

    // Initial pipeline state
    updatePipelineStages(document.getElementById("badge")?.dataset.status || "queued");

    // Elapsed timer (#15 fix: initialize from server started_at, not Date.now())
    var $elapsed = document.getElementById("elapsed-timer");
    var startTime = Date.now();
    // Try to read server-provided start time from data attribute
    var serverStart = page.dataset.startedAt;
    if (serverStart) {
        var parsed = new Date(serverStart).getTime();
        if (!isNaN(parsed)) startTime = parsed;
    }
    function updateElapsed() {
        if (!$elapsed || !polling) return;
        var secs = Math.floor((Date.now() - startTime) / 1000);
        var mins = Math.floor(secs / 60);
        var s = secs % 60;
        $elapsed.textContent = "Elapsed: " + mins + ":" + (s < 10 ? "0" : "") + s;
        setTimeout(updateElapsed, 1000);
    }
    updateElapsed();

    schedule();
})();
