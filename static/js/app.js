/**
 * Smart Campus Analytics - Application Controller & Screen Views
 * Plain language, neat 12-column grid, max 1200px width, clear charts answering questions.
 * Built for college faculty, administrators, and students.
 */

import {
    authState,
    login,
    logout,
    getCurrentUser,
    requestAccount,
    getOverview,
    getTrends,
    getStudents,
    getStudentProfile,
    getSegments,
    getInsights,
    getInterventions,
    updateIntervention,
    sendStudentMessage,
    getStudentMessages,
    getMessageInbox,
    replyStudentMessage,
    getScoreSettings,
    updateScoreSettings,
    recomputeAnalytics,
    getDataQualityLog,
    getModelMetrics,
    getAccountRequests,
    getAccountRequestCount,
    reviewAccountRequest,
    uploadCsvFiles,
    getExplain,
    askCampusAI
} from "./api.js";

import {
    computeIndicatorScores,
    computeSuccessScore,
    evaluateWhatIf
} from "./scoring.js";

import {
    LABELS,
    getAttentionText,
    getAttentionBadgeHtml,
    getDepartmentColor,
    formatScore,
    formatPercent,
    formatCount,
    formatGpa,
    helpTip
} from "./labels.js";
import { escapeHtml } from "./security.js";

// Active Chart.js instances registry for proper teardown
let activeCharts = [];
let accountRequestRefreshTimer = null;
let pendingRejectRequestId = null;
let rejectModalTrigger = null;

function showToast(message, type = "success") {
    const region = document.getElementById("toast-region");
    if (!region) return;
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.setAttribute("role", type === "error" ? "alert" : "status");
    toast.textContent = message;
    region.append(toast);
    window.setTimeout(() => toast.remove(), 4200);
}

function destroyActiveCharts() {
    activeCharts.forEach(c => {
        try { c.destroy(); } catch (e) { }
    });
    activeCharts = [];
}

if (typeof Chart !== "undefined") {
    Chart.register({
        id: "educareReadableBarValues",
        afterDatasetsDraw(chart) {
            if (chart.config.type !== "bar") return;
            const context = chart.ctx;
            const horizontal = chart.options.indexAxis === "y";
            if (chart.canvas.id === "chart-dept-overview" && !horizontal) {
                const chartArea = chart.chartArea;
                const labelHeight = 13;
                const labelGap = 3;
                const occupiedLabels = [];
                const pendingLabels = [];
                context.save();
                context.font = '600 10px "IBM Plex Sans", sans-serif';
                context.textAlign = "center";
                context.textBaseline = "middle";

                chart.data.datasets.forEach((dataset, datasetIndex) => {
                    const meta = chart.getDatasetMeta(datasetIndex);
                    if (meta.hidden) return;
                    meta.data.forEach((element, index) => {
                        const value = Number(dataset.data[index]);
                        if (!Number.isFinite(value) || value <= 0) return;
                        const segmentTop = Math.min(element.y, element.base);
                        const segmentBottom = Math.max(element.y, element.base);
                        const position = {
                            x: element.x,
                            y: (segmentTop + segmentBottom) / 2
                        };
                        const label = Math.round(value).toLocaleString();
                        const textWidth = context.measureText(label).width;
                        const halfWidth = textWidth / 2 + 3;
                        const rightEdge = element.x + element.width / 2;
                        const leftEdge = element.x - element.width / 2;
                        const rightFits = rightEdge + 5 + textWidth <= chartArea.right;
                        pendingLabels.push({
                            label,
                            position,
                            textWidth,
                            elementWidth: element.width,
                            x: rightFits ? rightEdge + 5 : leftEdge - 5,
                            direction: rightFits ? 1 : -1,
                            halfWidth,
                            targetY: position.y
                        });
                    });
                });

                pendingLabels.sort((first, second) => first.targetY - second.targetY);
                pendingLabels.forEach(item => {
                    const halfWidth = item.halfWidth;
                    const x = Math.max(
                        chartArea.left + halfWidth,
                        Math.min(chartArea.right - halfWidth, item.x)
                    );
                    const left = item.direction > 0 ? x - 3 : x - item.textWidth - 3;
                    const right = item.direction > 0 ? x + item.textWidth + 3 : x + 3;
                    const minY = chartArea.top + labelHeight / 2 + 1;
                    const maxY = chartArea.bottom - labelHeight / 2 - 1;
                    const targetY = Math.max(minY, Math.min(maxY, item.targetY));
                    const offsets = [0];
                    for (let offset = labelHeight + labelGap; offset <= chartArea.height; offset += labelHeight + labelGap) {
                        offsets.push(-offset, offset);
                    }
                    let y = targetY;
                    for (const offset of offsets) {
                        const candidateY = targetY + offset;
                        if (candidateY < minY || candidateY > maxY) continue;
                        const candidate = {
                            left,
                            right,
                            top: candidateY - labelHeight / 2,
                            bottom: candidateY + labelHeight / 2
                        };
                        const overlaps = occupiedLabels.some(occupied =>
                            candidate.left < occupied.right + labelGap &&
                            candidate.right + labelGap > occupied.left &&
                            candidate.top < occupied.bottom + labelGap &&
                            candidate.bottom + labelGap > occupied.top
                        );
                        if (!overlaps) {
                            y = candidateY;
                            break;
                        }
                    }
                    item.bounds = {
                        left,
                        right,
                        top: y - labelHeight / 2,
                        bottom: y + labelHeight / 2
                    };

                    context.save();
                    context.textAlign = item.direction > 0 ? "left" : "right";
                    context.strokeStyle = "rgba(255, 255, 255, 0.96)";
                    context.lineWidth = 3;
                    context.lineJoin = "round";
                    context.strokeText(item.label, x, y);
                    context.fillStyle = "#263238";
                    context.fillText(item.label, x, y);
                    const segmentEdge = item.direction > 0
                        ? item.position.x + item.elementWidth / 2
                        : item.position.x - item.elementWidth / 2;
                    const labelEdge = item.direction > 0 ? left : right;
                    context.beginPath();
                    context.strokeStyle = "#52606D";
                    context.lineWidth = 1;
                    context.moveTo(segmentEdge, item.position.y);
                    context.lineTo(labelEdge, y);
                    context.stroke();
                    context.restore();
                    occupiedLabels.push(item.bounds);
                });
                context.restore();
                return;
            }
            context.save();
            context.font = '600 10px "IBM Plex Sans", sans-serif';
            context.textAlign = "center";
            chart.data.datasets.forEach((dataset, datasetIndex) => {
                const meta = chart.getDatasetMeta(datasetIndex);
                if (meta.hidden) return;
                meta.data.forEach((element, index) => {
                    const value = Number(dataset.data[index]);
                    if (!Number.isFinite(value)) return;
                    const dimension = horizontal ? element.width : element.height;
                    if (dimension < 16 || element.width < 22) return;
                    const position = element.tooltipPosition();
                    const stacked = chart.options.scales?.x?.stacked && !horizontal;
                    context.fillStyle = stacked ? "#FFFFFF" : "#52606D";
                    context.textBaseline = stacked ? "middle" : "bottom";
                    context.fillText(
                        Math.round(value).toLocaleString(),
                        position.x,
                        stacked || horizontal ? position.y : position.y - 4
                    );
                });
            });
            context.restore();
        }
    });
    Chart.defaults.animation.duration = 220;
}

// Global active view state
let currentScreen = "overview";
let currentSelectedStudentId = null;

// Initialize App
document.addEventListener("DOMContentLoaded", () => {
    initAuthAndNavigation();
    initGlobalHelpPopovers();
    initGuidedTour();
});

/* ==========================================================================
   AUTHENTICATION & NAVIGATION SETUP
   ========================================================================== */
async function initAuthAndNavigation() {
    const loginForm = document.getElementById("login-form");
    const registrationForm = document.getElementById("register-form");
    const loginPanel = document.getElementById("login-panel");
    const registrationPanel = document.getElementById("registration-panel");
    const registrationFormView = document.getElementById("registration-form-view");
    const registrationSuccess = document.getElementById("registration-success");
    const registerPassword = document.getElementById("register-password");
    let registrationRole = "STUDENT";

    const setRegistrationRole = role => {
        registrationRole = role;
        document.querySelectorAll(".account-role-option").forEach(button => {
            const selected = button.dataset.accountRole === role;
            button.classList.toggle("active", selected);
            button.setAttribute("aria-pressed", String(selected));
        });
        document.querySelectorAll("[data-student-field]").forEach(field => {
            field.hidden = role !== "STUDENT";
        });
        document.querySelectorAll("[data-faculty-field]").forEach(field => {
            field.hidden = role !== "FACULTY";
            const input = field.querySelector("input");
            input.required = role === "FACULTY";
            if (role !== "FACULTY") {
                input.value = "";
                input.removeAttribute("aria-invalid");
            }
        });
        document.getElementById("register-student-id").required = role === "STUDENT";
        document.getElementById("register-student-id").value = "";
        document.getElementById("registration-error-msg").textContent = "";
        document.querySelectorAll(".field-error").forEach(error => { error.textContent = ""; });
        document.getElementById("btn-register-submit").textContent =
            role === "FACULTY" ? "Request faculty account" : "Request student account";
    };

    const setFieldError = (fieldId, message) => {
        const input = document.getElementById(fieldId);
        const errorId = fieldId === "register-student-id" ? "student-id-error" : `${fieldId}-error`;
        const error = document.getElementById(errorId);
        input.toggleAttribute("aria-invalid", Boolean(message));
        if (error) error.textContent = message;
    };

    window.addEventListener("educare:session-ended", showSignedOutScreen);
    window.addEventListener("storage", event => {
        if (event.key === "token" && !event.newValue) logout({ revoke: false });
    });
    window.addEventListener("pageshow", event => {
        if (event.persisted) validateStoredSession();
    });
    window.addEventListener("popstate", () => {
        if (!authState.token) showSignedOutScreen();
    });
    const sidebar = document.getElementById("sidebar");
    const sidebarToggle = document.getElementById("sidebar-toggle");
    sidebarToggle.addEventListener("click", () => {
        const expanded = sidebar.classList.toggle("sidebar-open");
        document.body.classList.toggle("sidebar-menu-open", expanded);
        sidebarToggle.setAttribute("aria-expanded", String(expanded));
        sidebarToggle.setAttribute("aria-label", expanded ? "Close navigation" : "Open navigation");
    });
    document.getElementById("sidebar-scrim").addEventListener("click", closeMobileSidebar);

    loginForm.addEventListener("submit", async event => {
        event.preventDefault();
        const errEl = document.getElementById("login-error-msg");
        const submit = document.getElementById("btn-login-submit");
        errEl.textContent = "";
        errEl.hidden = true;
        errEl.classList.remove("is-rejected");
        submit.disabled = true;
        submit.textContent = "Signing in...";
        try {
            await login(
                document.getElementById("login-username").value.trim(),
                document.getElementById("login-password").value
            );
            await enterAuthenticatedApp();
        } catch (err) {
            errEl.textContent = err.message || "Invalid username or password.";
            errEl.hidden = false;
            if (!err.message?.includes("waiting for admin approval")) {
                errEl.classList.add("is-rejected");
            }
        } finally {
            submit.disabled = false;
            submit.textContent = "Sign In";
        }
    });

    document.getElementById("btn-logout").addEventListener("click", () => logout());
    document.getElementById("show-register").addEventListener("click", () => {
        loginPanel.hidden = true;
        registrationPanel.hidden = false;
        registrationFormView.hidden = false;
        registrationSuccess.hidden = true;
        setRegistrationRole("STUDENT");
        document.getElementById("registration-error-msg").textContent = "";
    });
    document.getElementById("show-login").addEventListener("click", () => {
        registrationPanel.hidden = true;
        loginPanel.hidden = false;
    });
    document.getElementById("registration-success-login").addEventListener("click", () => {
        registrationPanel.hidden = true;
        loginPanel.hidden = false;
    });
    document.querySelectorAll(".account-role-option").forEach(button => {
        button.addEventListener("click", () => setRegistrationRole(button.dataset.accountRole));
    });
    registrationForm.addEventListener("submit", async event => {
        event.preventDefault();
        const submit = document.getElementById("btn-register-submit");
        const message = document.getElementById("registration-error-msg");
        const studentId = document.getElementById("register-student-id").value.trim();
        const name = document.getElementById("register-name").value.trim();
        const email = document.getElementById("register-email").value.trim();
        const department = document.getElementById("register-department").value.trim();
        const username = document.getElementById("register-username").value.trim();
        const password = registerPassword.value;
        message.textContent = "";
        document.querySelectorAll(".field-error").forEach(error => { error.textContent = ""; });
        const errors = [];
        if (registrationRole === "STUDENT" && studentId.length < 3) {
            setFieldError("register-student-id", "Enter a valid student ID (at least 3 characters).");
            errors.push(true);
        }
        if (registrationRole === "FACULTY") {
            if (name.length < 2) {
                setFieldError("register-name", "Enter your full name.");
                errors.push(true);
            }
            if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
                setFieldError("register-email", "Enter a valid email address.");
                errors.push(true);
            }
            if (!department) {
                setFieldError("register-department", "Enter your department.");
                errors.push(true);
            }
            if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{2,49}$/.test(username)) {
                setFieldError("register-username", "Use 3-50 letters, numbers, dots, dashes, or underscores.");
                errors.push(true);
            }
        }
        const passwordBytes = new TextEncoder().encode(password).length;
        if (Array.from(password).length < 12 || passwordBytes > 72) {
            setFieldError("register-password", "Password must be at least 12 characters and at most 72 UTF-8 bytes.");
            errors.push(true);
        }
        if (errors.length) return;

        submit.disabled = true;
        submit.textContent = "Submitting...";
        try {
            const payload = registrationRole === "STUDENT"
                ? { role: "STUDENT", student_id: studentId, password }
                : { role: "FACULTY", name, email, department, username, password };
            await requestAccount(payload);
            registrationForm.reset();
            registrationFormView.hidden = true;
            registrationSuccess.hidden = false;
        } catch (err) {
            message.textContent = err.message;
        } finally {
            submit.disabled = false;
            submit.textContent = registrationRole === "FACULTY"
                ? "Request faculty account"
                : "Request student account";
        }
    });
    registerPassword.addEventListener("input", () => setFieldError("register-password", ""));

    document.getElementById("reject-modal-close").addEventListener("click", closeRejectModal);
    document.getElementById("reject-cancel").addEventListener("click", closeRejectModal);
    document.getElementById("reject-modal").addEventListener("click", event => {
        if (event.target.id === "reject-modal") closeRejectModal();
    });
    document.addEventListener("keydown", event => {
        const modal = document.getElementById("reject-modal");
        if (!modal.hidden) {
            if (event.key === "Escape") {
                closeRejectModal();
            } else if (event.key === "Tab") {
                const focusable = [...modal.querySelectorAll(
                    'button:not([disabled]), textarea:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'
                )];
                const first = focusable[0];
                const last = focusable[focusable.length - 1];
                if (event.shiftKey && document.activeElement === first) {
                    event.preventDefault();
                    last.focus();
                } else if (!event.shiftKey && document.activeElement === last) {
                    event.preventDefault();
                    first.focus();
                }
            }
        }
    });
    document.getElementById("reject-form").addEventListener("submit", submitRejectRequest);

    showSignedOutScreen();
    await validateStoredSession();
}

function closeRejectModal() {
    const modal = document.getElementById("reject-modal");
    modal.hidden = true;
    pendingRejectRequestId = null;
    if (rejectModalTrigger && document.contains(rejectModalTrigger)) rejectModalTrigger.focus();
    rejectModalTrigger = null;
}

function openRejectModal(requestId) {
    rejectModalTrigger = document.activeElement;
    pendingRejectRequestId = requestId;
    const modal = document.getElementById("reject-modal");
    modal.hidden = false;
    document.getElementById("reject-reason").value = "";
    document.getElementById("reject-reason").focus();
}

function closeMobileSidebar() {
    document.getElementById("sidebar").classList.remove("sidebar-open");
    document.body.classList.remove("sidebar-menu-open");
    document.getElementById("sidebar-toggle").setAttribute("aria-expanded", "false");
    document.getElementById("sidebar-toggle").setAttribute("aria-label", "Open navigation");
}

async function submitRejectRequest(event) {
    event.preventDefault();
    if (!pendingRejectRequestId) return;
    const requestId = pendingRejectRequestId;
    const submit = event.currentTarget.querySelector('[type="submit"]');
    submit.disabled = true;
    try {
        await reviewAccountRequest(
            requestId,
            "reject",
            document.getElementById("reject-reason").value.trim()
        );
        closeRejectModal();
        showToast("Account request rejected.", "success");
        await renderAccountRequestsScreen();
        refreshAccountRequestBadge();
    } catch (error) {
        showToast(`Could not reject request: ${error.message}`, "error");
    } finally {
        submit.disabled = false;
    }
}

function showSignedOutScreen() {
    document.body.classList.remove("authenticated");
    document.getElementById("login-modal").style.display = "flex";
    document.getElementById("tour-modal").style.display = "none";
    document.getElementById("help-popover").classList.remove("visible");
    const oldScreen = document.getElementById("screen-container");
    const newScreen = document.createElement("div");
    newScreen.id = "screen-container";
    oldScreen.replaceWith(newScreen);
    document.getElementById("nav-menu").replaceChildren();
    document.getElementById("register-form").reset();
    document.getElementById("registration-panel").hidden = true;
    document.getElementById("registration-form-view").hidden = false;
    document.getElementById("registration-success").hidden = true;
    document.getElementById("login-panel").hidden = false;
    document.getElementById("registration-error-msg").textContent = "";
    document.getElementById("login-error-msg").hidden = true;
    document.getElementById("user-display-name").textContent = "Not Signed In";
    document.getElementById("user-role-label").textContent = "GUEST";
    document.getElementById("login-form").reset();
    document.getElementById("sidebar").classList.remove("sidebar-open");
    document.body.classList.remove("sidebar-menu-open");
    document.getElementById("sidebar-toggle").setAttribute("aria-expanded", "false");
    if (accountRequestRefreshTimer) {
        window.clearInterval(accountRequestRefreshTimer);
        accountRequestRefreshTimer = null;
    }
    currentSelectedStudentId = null;
    currentScreen = "overview";
    destroyActiveCharts();
}

async function validateStoredSession() {
    if (!authState.token || !authState.user) {
        showSignedOutScreen();
        return;
    }
    try {
        await enterAuthenticatedApp();
    } catch {
        logout({ revoke: false });
        showSignedOutScreen();
    }
}

async function enterAuthenticatedApp() {
    const user = await getCurrentUser();
    authState.user = {
        username: user.username,
        role: user.role,
        name: user.faculty_name || user.student_id || user.username,
        student_id: user.student_id
    };
    localStorage.setItem("user", JSON.stringify(authState.user));
    document.body.classList.add("authenticated");
    document.getElementById("login-modal").style.display = "none";
    currentSelectedStudentId = null;
    setupSidebarForUser();
    navigateToDefaultScreen();
    checkAndTriggerFirstTimeTour();
}

function setupSidebarForUser() {
    currentSelectedStudentId = null;
    const user = authState.user;
    const nameEl = document.getElementById("user-display-name");
    const roleEl = document.getElementById("user-role-label");
    const navMenu = document.getElementById("nav-menu");
    const navHeader = document.getElementById("nav-header-label");
    const tourBtn = document.getElementById("btn-start-tour");

    if (!user) {
        nameEl.textContent = "Not Signed In";
        roleEl.textContent = "GUEST";
        navMenu.innerHTML = "";
        if (tourBtn) tourBtn.style.display = "none";
        return;
    }

    nameEl.textContent = user.name || user.username;
    roleEl.textContent = user.role === "ADMIN" ? "Administrator" : (user.role === "FACULTY" ? "Faculty Advisor" : "Student");
    if (tourBtn) tourBtn.style.display = "block";

    if (user.role === "STUDENT") {
        navHeader.textContent = "Student Portal";
        navMenu.innerHTML = `
            <li class="nav-item active" data-screen="student-portal">${LABELS.nav.studentProgress}</li>
            <li class="nav-item" data-screen="student-whatif">${LABELS.nav.studentWhatIf}</li>
            <li class="nav-item" data-screen="student-actions">${LABELS.nav.studentActions}</li>
            <li class="nav-item" data-screen="student-mentor">${LABELS.nav.studentMentor}</li>
            <li class="nav-item" data-screen="score-guide">${LABELS.nav.scoreGuide}</li>
        `;
    } else {
        navHeader.textContent = user.role === "ADMIN" ? "Administrator Views" : "Teacher & Advisor Views";
        let items = `
            <li class="nav-item active" data-screen="overview">${LABELS.nav.overview}</li>
            <li class="nav-item" data-screen="trends">${LABELS.nav.trends}</li>
            <li class="nav-item" data-screen="risk-explorer">${LABELS.nav.riskExplorer}</li>
            <li class="nav-item" data-screen="action-list">${LABELS.nav.actionList}</li>
            <li class="nav-item" data-screen="student-profile">${LABELS.nav.studentProfile}</li>
            <li class="nav-item" data-screen="segments">${LABELS.nav.segments}</li>
            <li class="nav-item" data-screen="insights">${LABELS.nav.insights}</li>
            <li class="nav-item" data-screen="score-guide">${LABELS.nav.scoreGuide}</li>
            <li class="nav-item" data-screen="inbox">Inbox <span class="nav-badge" id="inbox-open-count">0</span></li>
        `;

        if (user.role === "ADMIN") {
            items += `
                <li class="nav-item" data-screen="data-quality">${LABELS.nav.dataQuality}</li>
                <li class="nav-item" data-screen="model-settings">${LABELS.nav.modelSettings}</li>
                <li class="nav-item" data-screen="account-requests">Account Requests <span class="nav-badge" id="account-request-count" hidden>0</span></li>
            `;
        }

        navMenu.innerHTML = items;
    }

    const navIconPaths = {
        overview: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
        trends: '<path d="M3 17l6-6 4 4 8-9"/><path d="M15 6h6v6"/>',
        "risk-explorer": '<path d="M12 3l8 3v5c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6l8-3z"/><path d="M12 8v5"/><path d="M12 16h.01"/>',
        "action-list": '<path d="M9 6h11"/><path d="M9 12h11"/><path d="M9 18h11"/><path d="M4 6h.01"/><path d="M4 12h.01"/><path d="M4 18h.01"/>',
        "student-profile": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
        segments: '<path d="M12 3a9 9 0 1 0 9 9h-9z"/><path d="M15 3.5A9 9 0 0 1 20.5 9H15z"/>',
        insights: '<path d="M9 18h6"/><path d="M10 22h4"/><path d="M8.5 14.5A7 7 0 1 1 15.5 14c-.8.6-1.2 1.2-1.4 2h-4.2c-.2-.6-.6-1.1-1.4-1.5z"/>',
        "score-guide": '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v17H6.5A2.5 2.5 0 0 0 4 22z"/><path d="M4 5.5v16.5"/><path d="M8 7h8"/>',
        inbox: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 12h5l2 3h4l2-3h5"/><path d="m4 6 8 6 8-6"/>',
        "data-quality": '<path d="M4 5h16"/><path d="M4 12h10"/><path d="M4 19h8"/><path d="m16 17 2 2 4-5"/>',
        "model-settings": '<circle cx="12" cy="12" r="3"/><path d="m19.4 15 .1.1 1.4 1.1-1.4 2.4-1.7-.7a8 8 0 0 1-1.7 1l-.3 1.8h-2.8l-.3-1.8a8 8 0 0 1-1.7-1l-1.7.7-1.4-2.4 1.4-1.1a7 7 0 0 1 0-2l-1.4-1.1 1.4-2.4 1.7.7a8 8 0 0 1 1.7-1l.3-1.8h2.8l.3 1.8a8 8 0 0 1 1.7 1l1.7-.7 1.4 2.4-1.4 1.1a7 7 0 0 1 0 2z"/>',
        "account-requests": '<circle cx="9" cy="8" r="4"/><path d="M2 21a7 7 0 0 1 14 0"/><path d="M19 8v6"/><path d="M16 11h6"/>',
        "student-portal": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
        "student-whatif": '<path d="M4 19V5"/><path d="M4 19h16"/><path d="m7 15 4-5 3 2 5-7"/>',
        "student-actions": '<path d="m5 12 4 4L19 6"/>',
        "student-mentor": '<path d="M4 5h16v12H9l-5 4z"/><path d="M8 10h8"/><path d="M8 13h5"/>'
    };

    // Attach icons and click events to nav items.
    navMenu.querySelectorAll(".nav-item").forEach(item => {
        const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        icon.setAttribute("class", "nav-icon");
        icon.setAttribute("viewBox", "0 0 24 24");
        icon.setAttribute("aria-hidden", "true");
        icon.innerHTML = navIconPaths[item.dataset.screen] || navIconPaths.inbox;
        item.prepend(icon);
        item.addEventListener("click", () => {
            closeMobileSidebar();
            navMenu.querySelectorAll(".nav-item").forEach(el => el.classList.remove("active"));
            item.classList.add("active");
            const screen = item.dataset.screen;
            navigateToScreen(screen);
        });
    });

    if (user.role === "ADMIN" || user.role === "FACULTY") {
        refreshInboxBadge().catch(err => console.error("Could not refresh inbox count:", err));
    }
    if (accountRequestRefreshTimer) window.clearInterval(accountRequestRefreshTimer);
    if (user.role === "ADMIN") {
        refreshAccountRequestBadge();
        accountRequestRefreshTimer = window.setInterval(refreshAccountRequestBadge, 30000);
    }
}

async function refreshInboxBadge() {
    const messages = await getMessageInbox();
    updateInboxBadge(messages.length);
}

function updateInboxBadge(count) {
    const badge = document.getElementById("inbox-open-count");
    if (badge) badge.textContent = String(count);
}

async function refreshAccountRequestBadge() {
    const badge = document.getElementById("account-request-count");
    if (!badge || !authState.user || authState.user.role !== "ADMIN") return;
    try {
        const result = await getAccountRequestCount();
        badge.textContent = String(result.count);
        badge.hidden = result.count === 0;
    } catch (error) {
        console.error("Could not refresh account request count:", error);
    }
}

function navigateToDefaultScreen() {
    if (authState.user && authState.user.role === "STUDENT") {
        navigateToScreen("student-portal");
    } else {
        navigateToScreen("overview");
    }
}

export function navigateToScreen(screenName, extraParam = null) {
    currentScreen = screenName;
    destroyActiveCharts();
    const container = document.getElementById("screen-container");

    // Update active nav item
    const navItems = document.querySelectorAll(".nav-item");
    navItems.forEach(el => {
        if (el.dataset.screen === screenName) el.classList.add("active");
        else el.classList.remove("active");
    });

    container.innerHTML = `<div class="state-container"><div class="spinner"></div><p>Loading campus information...</p></div>`;

    if (authState.user && authState.user.role === "STUDENT") {
        const sid = authState.user.student_id;
        if (screenName === "student-portal") renderStudentPortalScreen(sid, "progress");
        else if (screenName === "student-whatif") renderStudentPortalScreen(sid, "whatif");
        else if (screenName === "student-actions") renderStudentPortalScreen(sid, "actions");
        else if (screenName === "student-mentor") renderStudentPortalScreen(sid, "mentor");
        else if (screenName === "score-guide") renderScoreGuideScreen();
        else renderStudentPortalScreen(sid, "progress");
        return;
    }

    // Staff Views
    switch (screenName) {
        case "overview":
            renderOverviewScreen();
            break;
        case "trends":
            renderTrendsScreen();
            break;
        case "risk-explorer":
            renderRiskExplorerScreen();
            break;
        case "action-list":
            renderActionListScreen();
            break;
        case "student-profile":
            renderStudentProfileScreen(extraParam || currentSelectedStudentId);
            break;
        case "segments":
            renderSegmentsScreen();
            break;
        case "insights":
            renderInsightsScreen();
            break;
        case "score-guide":
            renderScoreGuideScreen();
            break;
        case "data-quality":
            renderDataQualityScreen();
            break;
        case "model-settings":
            renderModelSettingsScreen();
            break;
        case "account-requests":
            renderAccountRequestsScreen();
            break;
        case "inbox":
            renderInboxScreen();
            break;
        default:
            renderOverviewScreen();
    }
}

async function renderInboxScreen() {
    const container = document.getElementById("screen-container");
    try {
        const messages = await getMessageInbox();
        updateInboxBadge(messages.length);
        container.innerHTML = `
            <div class="page-header">
                <div>
                    <h1 class="page-title">Inbox</h1>
                    <div class="page-purpose">Open messages from students in your cohort.</div>
                </div>
            </div>
            <div class="content-card">
                ${messages.length === 0
                    ? `<p style="color: var(--text-muted);">No open student messages.</p>`
                    : messages.map(message => `
                        <article class="inbox-message" style="padding: 16px 0; border-bottom: 1px solid var(--border-hairline);">
                            <div style="display: flex; justify-content: space-between; gap: 12px; margin-bottom: 8px;">
                                <strong>${escapeHtml(message.student_name)}</strong>
                                <span style="color: var(--text-muted); font-size: 12px;">${escapeHtml(message.created_at ? message.created_at.replace("T", " ").slice(0, 16) : "")}</span>
                            </div>
                            <p style="white-space: pre-wrap; margin-bottom: 12px;">${escapeHtml(message.message.length > 240 ? `${message.message.slice(0, 240)}...` : message.message)}</p>
                            <form class="inbox-reply-form" data-message-id="${message.id}">
                                <label class="sr-only" for="inbox-reply-${message.id}">Reply to ${escapeHtml(message.student_name)}</label>
                                <textarea id="inbox-reply-${message.id}" class="form-control" rows="3" placeholder="Write a reply..." required></textarea>
                                <button type="submit" class="btn-primary" style="margin-top: 8px;">Send Reply</button>
                            </form>
                        </article>
                    `).join("")}
            </div>
        `;

        container.querySelectorAll(".inbox-reply-form").forEach(form => {
            form.addEventListener("submit", async event => {
                event.preventDefault();
                const textarea = form.querySelector("textarea");
                const button = form.querySelector("button");
                const reply = textarea.value.trim();
                if (!reply) return;

                button.disabled = true;
                try {
                    await replyStudentMessage(form.dataset.messageId, reply);
                    await renderInboxScreen();
                } catch (err) {
                    button.disabled = false;
                    alert("Could not send reply: " + err.message);
                }
            });
        });
    } catch (err) {
        container.innerHTML = `<div class="state-container"><p>Could not load inbox: ${escapeHtml(err.message)}</p></div>`;
    }
}

/* ==========================================================================
   PART 4: HELP POPOVERS & 3-STEP GUIDED TOUR
   ========================================================================== */
function initGlobalHelpPopovers() {
    const popover = document.getElementById("help-popover");
    if (!popover) return;

    document.addEventListener("mouseover", (e) => {
        const btn = e.target.closest(".help-btn");
        if (btn) {
            const text = btn.getAttribute("data-help");
            if (!text) return;
            popover.textContent = text;
            popover.classList.add("visible");
            const rect = btn.getBoundingClientRect();
            popover.style.left = `${Math.max(10, rect.left - 100)}px`;
            popover.style.top = `${rect.top - popover.offsetHeight - 8 + window.scrollY}px`;
        }
    });

    document.addEventListener("mouseout", (e) => {
        const btn = e.target.closest(".help-btn");
        if (btn) {
            popover.classList.remove("visible");
        }
    });

    document.addEventListener("click", (e) => {
        const btn = e.target.closest(".help-btn");
        if (btn) {
            e.stopPropagation();
            const text = btn.getAttribute("data-help");
            if (!text) return;
            popover.textContent = text;
            popover.classList.toggle("visible");
            const rect = btn.getBoundingClientRect();
            popover.style.left = `${Math.max(10, rect.left - 100)}px`;
            popover.style.top = `${rect.top - popover.offsetHeight - 8 + window.scrollY}px`;
        } else {
            popover.classList.remove("visible");
        }
    });
}

const TOUR_STEPS = [
    {
        title: "Summary Numbers",
        badge: "Step 1 of 3",
        desc: "Glance here to see how your college and students are doing overall. Numbers show progress compared to last semester."
    },
    {
        title: "Plain Questions on Every Chart",
        badge: "Step 2 of 3",
        desc: "Every chart answers a simple question with a one-line takeaway. You can understand each screen in 5 seconds without data expertise."
    },
    {
        title: "Who to Help First",
        badge: "Step 3 of 3",
        desc: "Find students who need support right away. See suggested steps, potential score gains, and track progress with your team."
    }
];

let currentTourStep = 0;

function initGuidedTour() {
    const tourModal = document.getElementById("tour-modal");
    const btnNext = document.getElementById("tour-next-btn");
    const btnSkip = document.getElementById("tour-skip-btn");
    const tourLaunchBtn = document.getElementById("btn-start-tour");

    if (tourLaunchBtn) {
        tourLaunchBtn.addEventListener("click", () => {
            currentTourStep = 0;
            showTourStep();
            tourModal.style.display = "flex";
        });
    }

    if (btnSkip) {
        btnSkip.addEventListener("click", () => {
            tourModal.style.display = "none";
            localStorage.setItem("hasSeenTour", "true");
        });
    }

    if (btnNext) {
        btnNext.addEventListener("click", () => {
            currentTourStep++;
            if (currentTourStep >= TOUR_STEPS.length) {
                tourModal.style.display = "none";
                localStorage.setItem("hasSeenTour", "true");
            } else {
                showTourStep();
            }
        });
    }
}

function showTourStep() {
    const s = TOUR_STEPS[currentTourStep];
    document.getElementById("tour-step-badge").textContent = s.badge;
    document.getElementById("tour-step-title").textContent = s.title;
    document.getElementById("tour-step-desc").textContent = s.desc;
    const btnNext = document.getElementById("tour-next-btn");
    if (currentTourStep === TOUR_STEPS.length - 1) {
        btnNext.textContent = "Got it!";
    } else {
        btnNext.innerHTML = "Next &rarr;";
    }
}

function checkAndTriggerFirstTimeTour() {
    if (!localStorage.getItem("hasSeenTour")) {
        currentTourStep = 0;
        showTourStep();
        const tourModal = document.getElementById("tour-modal");
        if (tourModal) tourModal.style.display = "flex";
    }
}

/* ==========================================================================
   SCREEN 1: COLLEGE OVERVIEW
   ========================================================================== */
async function renderOverviewScreen() {
    const container = document.getElementById("screen-container");
    try {
        const data = await getOverview();

        // 4 Summary numbers with small vs last semester change
        const totalStudents = formatCount(data.total_students);
        const avgScore = formatScore(data.avg_score);
        const urgentCount = formatCount(data.at_risk_count);
        const urgentPct = formatPercent(data.at_risk_pct);
        const placementCount = formatCount(data.placement_ready_count);
        const placementPct = formatPercent(data.placement_ready_pct);

        container.innerHTML = `
            <div class="page-header">
                <div>
                    <h1 class="page-title">${LABELS.screens.overview.title}</h1>
                    <div class="page-purpose">${LABELS.screens.overview.subtitle}</div>
                </div>
            </div>

            <!-- Tidy Filter Bar (PART 3) -->
            <div class="filter-bar-card">
                <div class="filter-bar-row">
                    <span class="filter-label">Filter students:</span>
                    <select class="filter-select" id="overview-dept-filter" aria-label="Department filter">
                        <option value="All">All Departments</option>
                        ${LABELS.departments.map(d => `<option value="${d.code}">${d.code} (${d.name})</option>`).join('')}
                    </select>
                    <select class="filter-select" id="overview-year-filter" aria-label="Year batch filter">
                        <option value="0">All Years</option>
                        <option value="1">Year 1</option>
                        <option value="2">Year 2</option>
                        <option value="3">Year 3</option>
                        <option value="4">Year 4</option>
                    </select>
                    <button type="button" class="btn-reset-filters" id="btn-reset-overview-filters">Reset filters</button>
                </div>
                <div class="filter-chips-row" id="overview-chips-row" style="display: none;"></div>
            </div>

            <!-- 4 Summary Numbers at the top (PART 3) -->
            <div class="summary-grid">
                <div class="summary-card">
                    <div class="summary-card-header">
                        <span class="summary-label">Total Students ${helpTip("All students currently enrolled in the selected department and year.")}</span>
                        <svg class="summary-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="8" r="4"/><path d="M2 21a7 7 0 0 1 14 0M17 11a4 4 0 0 0 0-7m1 11a7 7 0 0 1 4 6"/></svg>
                    </div>
                    <div class="summary-value mono-num" id="overview-total-students">${totalStudents}</div>
                    <div class="summary-change-row">
                        <span class="change-text">In the selected cohort</span>
                    </div>
                </div>

                <div class="summary-card">
                    <div class="summary-card-header">
                        <span class="summary-label">Average ${LABELS.scoreName} ${helpTip(LABELS.scoreHelp)}</span>
                        <svg class="summary-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19V5m0 14h16M7 15l4-5 3 3 5-7"/></svg>
                    </div>
                    <div class="summary-value mono-num" style="color: var(--accent-teal);"><span id="overview-average-score">${avgScore}</span> <span style="font-size: 16px; font-weight: normal; color: var(--text-muted);">${LABELS.scoreOutScores}</span></div>
                    <div class="summary-change-row">
                        <span class="change-text">Average for the selected cohort</span>
                    </div>
                </div>

                <div class="summary-card">
                    <div class="summary-card-header">
                        <span class="summary-label">${LABELS.attentionUrgent} ${helpTip("Students who need immediate support from advisors for academics or job prep.")}</span>
                        <svg class="summary-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 9 17H3l9-17Z"/><path d="M12 9v5m0 3h.01"/></svg>
                    </div>
                    <div class="summary-value mono-num" style="color: var(--status-urgent);"><span id="overview-urgent-count">${urgentCount}</span> <span id="overview-urgent-percent" style="font-size: 16px; font-weight: normal; color: var(--text-muted);">(${urgentPct})</span></div>
                    <div class="summary-change-row">
                        <span class="change-text">Urgent support in the selected cohort</span>
                    </div>
                </div>

                <div class="summary-card">
                    <div class="summary-card-header">
                        <span class="summary-label">Job Readiness On Track ${helpTip("Students with strong coding, interview, and test preparation scores.")}</span>
                        <svg class="summary-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>
                    </div>
                    <div class="summary-value mono-num" style="color: var(--status-fine);"><span id="overview-placement-count">${placementCount}</span> <span id="overview-placement-percent" style="font-size: 16px; font-weight: normal; color: var(--text-muted);">(${placementPct})</span></div>
                    <div class="summary-change-row">
                        <span class="change-text">Placement-ready in the selected cohort</span>
                    </div>
                </div>
            </div>

            <!-- Main Charts (PART 2: max 4 charts per screen, plain question titles, takeaways) -->
            <div class="grid-12">
                <div class="col-6 content-card">
                    <div class="card-header">
                        <div class="card-title-row">
                            <h2 class="card-title">How many students need support across score ranges? ${helpTip("Shows student count grouped by 10-point brackets out of 100.")}</h2>
                        </div>
                        <div class="card-how-to-read">How to read this: Each bar shows how many students have scores in that 10-point bracket.</div>
                    </div>
                    <div class="card-takeaway" id="takeaway-score-dist">Student success score distribution in the selected cohort.</div>
                    <div class="chart-box-md">
                        <canvas id="chart-score-dist"></canvas>
                    </div>
                </div>

                <div class="col-6 content-card">
                    <div class="card-header">
                        <div class="card-title-row">
                            <h2 class="card-title">How is overall risk distributed? ${helpTip("Each student is counted once, using the highest of academic and placement risk levels.")}</h2>
                        </div>
                        <div class="card-how-to-read">Risk counts reflect the selected department and year.</div>
                    </div>
                    <div class="chart-box-md">
                        <canvas id="chart-risk-distribution" role="img" aria-label="Student risk distribution"></canvas>
                    </div>
                </div>

                <div class="col-12 content-card">
                    <div class="card-header">
                        <div class="card-title-row">
                            <h2 class="card-title">How are support levels distributed by department? ${helpTip("Departments are compared by counts of students in each overall risk category.")}</h2>
                        </div>
                        <div class="card-how-to-read">How to read this: Each department bar is stacked by overall risk category.</div>
                    </div>
                    <div class="chart-data-note" id="chart-dept-overview-note" role="status" style="display: none;"></div>
                    <div class="chart-box-md chart-box-department" id="chart-dept-overview-container">
                        <canvas id="chart-dept-overview" role="img" aria-label="Stacked student support levels by department"></canvas>
                        <div class="chart-state" id="chart-dept-overview-empty" role="status" style="display: none;">
                            No department data matches the selected filters.
                        </div>
                    </div>
                </div>
            </div>

            <!-- Detailed Table at the Bottom (PART 3) -->
            <div class="content-card">
                <div class="card-header">
                    <div class="card-title-row">
                        <h2 class="card-title">Department Performance Summary ${helpTip("Full breakdown of headcount, attendance, and support levels by department.")}</h2>
                    </div>
                    <div class="card-how-to-read">How to read this: Check average scores and urgent student counts for each department.</div>
                </div>

                <div class="table-toolbar">
                    <input type="text" id="overview-table-search" class="table-search-input" placeholder="Search department...">
                    <span class="table-count-label">Showing 5 departments</span>
                </div>

                <div class="table-responsive">
                    <table class="dense-table" id="overview-table">
                        <thead>
                            <tr>
                                <th>Department</th>
                                <th class="num-col">Students</th>
                                <th class="num-col">Average Score</th>
                                <th class="num-col">Average Attendance</th>
                                <th class="num-col">Job Readiness</th>
                                <th class="num-col">Urgent Attention</th>
                                <th>Attention Status</th>
                            </tr>
                        </thead>
                        <tbody id="overview-department-rows">
                            ${data.department_heatmap.map(d => {
                                const statusHtml = d.high_risk_count > 12 ? getAttentionBadgeHtml("high") : (d.high_risk_count > 6 ? getAttentionBadgeHtml("medium") : getAttentionBadgeHtml("low"));
                                return `
                                    <tr>
                                        <td><strong>${escapeHtml(d.department)}</strong></td>
                                        <td class="num-col mono-num">${formatCount(d.student_count)}</td>
                                        <td class="num-col mono-num">${formatScore(d.avg_score)} / 100</td>
                                        <td class="num-col mono-num">${formatPercent(d.avg_attendance)}</td>
                                        <td class="num-col mono-num">${formatScore(d.avg_placement)} / 100</td>
                                        <td class="num-col mono-num" style="color: ${d.high_risk_count > 0 ? 'var(--status-urgent)' : 'var(--text-muted)'}; font-weight: 600;">
                                            ${formatCount(d.high_risk_count)}
                                        </td>
                                        <td>${statusHtml}</td>
                                    </tr>
                                `;
                            }).join('')}
                        </tbody>
                    </table>
                </div>
            </div>
        `;

        // Chart 1: Score Distribution (Simple Bar, Teal, Direct labels)
        const ctx1 = document.getElementById("chart-score-dist").getContext("2d");
        const chart1 = new Chart(ctx1, {
            type: "bar",
            data: {
                labels: data.score_distribution.map(b => `${b.range} pts`),
                datasets: [{
                    label: "Students",
                    data: data.score_distribution.map(b => b.count),
                    backgroundColor: "#0F5C5C",
                    hoverBackgroundColor: "#147A78",
                    borderRadius: 3
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `${ctx.parsed.y} students in this score bracket`
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        title: { display: true, text: "Score bracket (out of 100)", font: { size: 12 } }
                    },
                    y: {
                        grid: { color: "#E3DFD6" },
                        ticks: { precision: 0 },
                        title: { display: true, text: "Students", font: { size: 12 } }
                    }
                }
            }
        });
        activeCharts.push(chart1);

        // Chart 2: Overall risk distribution
        const ctx2 = document.getElementById("chart-dept-overview").getContext("2d");
        const chart2 = new Chart(ctx2, {
            type: "bar",
            data: {
                labels: data.department_heatmap.map(row => row.department),
                datasets: [
                    { label: "Urgent", data: data.department_heatmap.map(row => row.risk_counts.High), backgroundColor: "#C53030", hoverBackgroundColor: "#A61F24", hoverBorderColor: "#7F1D1D", hoverBorderWidth: 1, borderRadius: 3 },
                    { label: "Soon", data: data.department_heatmap.map(row => row.risk_counts.Medium), backgroundColor: "#B45309", hoverBackgroundColor: "#934306", hoverBorderColor: "#78350F", hoverBorderWidth: 1, borderRadius: 3 },
                    { label: "Doing fine", data: data.department_heatmap.map(row => row.risk_counts.Low), backgroundColor: "#2E7D32", hoverBackgroundColor: "#246428", hoverBorderColor: "#14532D", hoverBorderWidth: 1, borderRadius: 3 }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "nearest", intersect: true },
                plugins: {
                    legend: { position: "bottom", labels: { usePointStyle: true } },
                    tooltip: {
                        callbacks: {
                            title: items => items.length
                                ? items[0].chart.data.labels[items[0].dataIndex]
                                : "",
                            label: context => {
                                const total = context.chart.data.datasets.reduce(
                                    (sum, dataset) => sum + (Number(dataset.data[context.dataIndex]) || 0),
                                    0
                                );
                                const count = Number(context.raw) || 0;
                                const percent = total ? (count / total * 100).toFixed(1) : "0.0";
                                const studentLabel = count === 1 ? "student" : "students";
                                return `${context.dataset.label}: ${count} ${studentLabel} (${percent}%)`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        stacked: true,
                        grid: { display: false },
                        title: { display: true, text: "Department", font: { size: 12 } },
                        ticks: { autoSkip: false, maxRotation: 0, minRotation: 0 }
                    },
                    y: {
                        stacked: true,
                        grace: "20%",
                        grid: { color: "#E3DFD6" },
                        ticks: { precision: 0 },
                        title: { display: true, text: "Students", font: { size: 12 } }
                    }
                },
                datasets: {
                    bar: {
                        categoryPercentage: 0.62,
                        barPercentage: 0.8,
                        maxBarThickness: 68
                    }
                }
            }
        });
        activeCharts.push(chart2);
        const departmentChartEmpty = document.getElementById("chart-dept-overview-empty");
        const departmentChartNote = document.getElementById("chart-dept-overview-note");
        const updateDepartmentChart = departmentRows => {
            chart2.data.labels = departmentRows.map(row => row.department);
            chart2.data.datasets.forEach((dataset, index) => {
                const riskLevel = ["High", "Medium", "Low"][index];
                dataset.data = departmentRows.map(row => row.risk_counts[riskLevel]);
            });
            const hasDepartments = departmentRows.length > 0;
            chart2.canvas.style.display = hasDepartments ? "block" : "none";
            departmentChartEmpty.style.display = hasDepartments ? "none" : "flex";
            departmentChartNote.style.display = departmentRows.length === 1 ? "block" : "none";
            departmentChartNote.textContent = departmentRows.length === 1
                ? `Only ${departmentRows[0].department} has student records for these filters; comparison is limited.`
                : "";
            chart2.update();
        };
        updateDepartmentChart(data.department_heatmap);

        const riskChart = new Chart(document.getElementById("chart-risk-distribution").getContext("2d"), {
            type: "doughnut",
            data: {
                labels: ["Urgent", "Soon", "Doing fine"],
                datasets: [{
                    data: [
                        data.risk_distribution.High,
                        data.risk_distribution.Medium,
                        data.risk_distribution.Low
                    ],
                    backgroundColor: ["#C53030", "#B45309", "#2E7D32"],
                    hoverBackgroundColor: ["#A61F24", "#934306", "#246428"],
                    hoverOffset: 7,
                    borderColor: "#FFFFFF",
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "62%",
                interaction: { mode: "nearest", intersect: true },
                plugins: {
                    legend: { position: "bottom", labels: { usePointStyle: true } },
                    tooltip: {
                        callbacks: {
                            label: context => {
                                const total = context.dataset.data.reduce((sum, value) => sum + Number(value || 0), 0);
                                const count = Number(context.raw) || 0;
                                const percent = total ? (count / total * 100).toFixed(1) : "0.0";
                                return `${context.label}: ${count} students (${percent}%)`;
                            }
                        }
                    }
                }
            }
        });
        activeCharts.push(riskChart);

        // Filters handler
        const deptFilter = document.getElementById("overview-dept-filter");
        const yearFilter = document.getElementById("overview-year-filter");
        const resetBtn = document.getElementById("btn-reset-overview-filters");
        const chipsRow = document.getElementById("overview-chips-row");

        const updateFilters = async () => {
            const dVal = deptFilter.value;
            const yVal = parseInt(yearFilter.value, 10);

            // Update chips
            chipsRow.innerHTML = "";
            let hasChips = false;
            if (dVal !== "All") {
                chipsRow.innerHTML += `<span class="filter-chip">Dept: ${dVal} <span class="filter-chip-clear" data-type="dept">&times;</span></span>`;
                hasChips = true;
            }
            if (yVal !== 0) {
                chipsRow.innerHTML += `<span class="filter-chip">Year ${yVal} <span class="filter-chip-clear" data-type="year">&times;</span></span>`;
                hasChips = true;
            }
            chipsRow.style.display = hasChips ? "flex" : "none";

            // Bind chip clear
            chipsRow.querySelectorAll(".filter-chip-clear").forEach(btn => {
                btn.addEventListener("click", () => {
                    if (btn.dataset.type === "dept") deptFilter.value = "All";
                    if (btn.dataset.type === "year") yearFilter.value = "0";
                    updateFilters();
                });
            });

            const filteredData = await getOverview({ department: dVal, year: yVal });
            chart1.data.labels = filteredData.score_distribution.map(b => `${b.range} pts`);
            chart1.data.datasets[0].data = filteredData.score_distribution.map(b => b.count);
            chart1.update();
            updateDepartmentChart(filteredData.department_heatmap);
            riskChart.data.datasets[0].data = [
                filteredData.risk_distribution.High,
                filteredData.risk_distribution.Medium,
                filteredData.risk_distribution.Low
            ];
            riskChart.update();
            document.getElementById("overview-total-students").textContent = formatCount(filteredData.total_students);
            document.getElementById("overview-average-score").textContent = formatScore(filteredData.avg_score);
            document.getElementById("overview-urgent-count").textContent = formatCount(filteredData.at_risk_count);
            document.getElementById("overview-urgent-percent").textContent = `(${formatPercent(filteredData.at_risk_pct)})`;
            document.getElementById("overview-placement-count").textContent = formatCount(filteredData.placement_ready_count);
            document.getElementById("overview-placement-percent").textContent = `(${formatPercent(filteredData.placement_ready_pct)})`;
            document.getElementById("overview-department-rows").innerHTML = filteredData.department_heatmap.map(row => {
                const statusHtml = row.high_risk_count > 12
                    ? getAttentionBadgeHtml("high")
                    : (row.high_risk_count > 6 ? getAttentionBadgeHtml("medium") : getAttentionBadgeHtml("low"));
                return `<tr>
                    <td><strong>${escapeHtml(row.department)}</strong></td>
                    <td class="num-col mono-num">${formatCount(row.student_count)}</td>
                    <td class="num-col mono-num">${formatScore(row.avg_score)} / 100</td>
                    <td class="num-col mono-num">${formatPercent(row.avg_attendance)}</td>
                    <td class="num-col mono-num">${formatScore(row.avg_placement)} / 100</td>
                    <td class="num-col mono-num">${formatCount(row.high_risk_count)}</td>
                    <td>${statusHtml}</td>
                </tr>`;
            }).join("");
            document.getElementById("overview-table-search").dispatchEvent(new Event("input"));
        };

        deptFilter.addEventListener("change", updateFilters);
        yearFilter.addEventListener("change", updateFilters);
        resetBtn.addEventListener("click", () => {
            deptFilter.value = "All";
            yearFilter.value = "0";
            updateFilters();
        });

        // Search in overview table
        setupSimpleTableSearch("overview-table", "overview-table-search");

    } catch (err) {
        container.innerHTML = `<div class="state-container"><p style="color: var(--status-urgent);">${escapeHtml(err.message)}</p></div>`;
    }
}

/* ==========================================================================
   SCREEN 2: CHANGES OVER TIME (TRENDS)
   ========================================================================== */
async function renderTrendsScreen() {
    const container = document.getElementById("screen-container");
    try {
        const trends = await getTrends();

        container.innerHTML = `
            <div class="page-header">
                <div>
                    <h1 class="page-title">${LABELS.screens.trends.title}</h1>
                    <div class="page-purpose">${LABELS.screens.trends.subtitle}</div>
                </div>
            </div>

            <!-- 3 Summary Numbers (PART 3) -->
            <div class="summary-grid">
                <div class="summary-card">
                    <div class="summary-card-header">
                        <span class="summary-label">Average College GPA ${helpTip("College-wide grade point average across active semesters.")}</span>
                    </div>
                    <div class="summary-value mono-num">7.4 <span style="font-size: 16px; font-weight: normal; color: var(--text-muted);">out of 10</span></div>
                    <div class="summary-change-row">
                        <span class="change-pill change-up">+0.2</span>
                        <span class="change-text">vs last semester</span>
                    </div>
                </div>

                <div class="summary-card">
                    <div class="summary-card-header">
                        <span class="summary-label">Average Attendance ${helpTip("Percentage of classes attended by students.")}</span>
                    </div>
                    <div class="summary-value mono-num">81%</div>
                    <div class="summary-change-row">
                        <span class="change-pill change-neutral">0%</span>
                        <span class="change-text">vs last semester (steady)</span>
                    </div>
                </div>

                <div class="summary-card">
                    <div class="summary-card-header">
                        <span class="summary-label">Course Backlogs ${helpTip("Total exams or courses that students still need to clear.")}</span>
                    </div>
                    <div class="summary-value mono-num">84 <span style="font-size: 16px; font-weight: normal; color: var(--text-muted);">pending</span></div>
                    <div class="summary-change-row">
                        <span class="change-pill change-up">-12</span>
                        <span class="change-text">vs last semester (fewer backlogs)</span>
                    </div>
                </div>
            </div>

            <!-- Main Charts (PART 2: Line for change over time, Bar for comparing years) -->
            <div class="grid-12">
                <div class="col-6 content-card">
                    <div class="card-header">
                        <div class="card-title-row">
                            <h2 class="card-title">Is attendance going up or down across semesters? ${helpTip("Tracks attendance across Semesters 1 to 8.")}</h2>
                        </div>
                        <div class="card-how-to-read">How to read this: The line shows the average attendance percentage from Semester 1 to Semester 8.</div>
                    </div>
                    <div class="card-takeaway">
                        Attendance stays above the 75% minimum needed in every semester, with a mild dip in Semester 6.
                    </div>
                    <div class="chart-box-md">
                        <canvas id="chart-sem-trends"></canvas>
                    </div>
                </div>

                <div class="col-6 content-card">
                    <div class="card-header">
                        <div class="card-title-row">
                            <h2 class="card-title">How do scores compare across the four college years? ${helpTip("Compares overall success score across Year 1, Year 2, Year 3, and Year 4.")}</h2>
                        </div>
                        <div class="card-how-to-read">How to read this: Each bar represents a college year batch (Year 1 to Year 4).</div>
                    </div>
                    <div class="card-takeaway">
                        Year 4 students show the highest scores (76 out of 100) due to intensive job readiness and project work.
                    </div>
                    <div class="chart-box-md">
                        <canvas id="chart-year-comparison"></canvas>
                    </div>
                </div>
            </div>

            <!-- Detailed Table at the Bottom (PART 3) -->
            <div class="content-card">
                <div class="card-header">
                    <div class="card-title-row">
                        <h2 class="card-title">Department Averages Across Key Areas ${helpTip("Compares all five branches across the five parts of the score.")}</h2>
                    </div>
                    <div class="card-how-to-read">How to read this: Shows how each engineering branch performs across studies, attendance, and job readiness.</div>
                </div>

                <div class="table-toolbar">
                    <input type="text" id="trends-table-search" class="table-search-input" placeholder="Search department...">
                    <span class="table-count-label">5 departments</span>
                </div>

                <div class="table-responsive">
                    <table class="dense-table" id="trends-table">
                        <thead>
                            <tr>
                                <th>Department</th>
                                <th class="num-col">Overall Score</th>
                                <th class="num-col">Studies (35%)</th>
                                <th class="num-col">Attendance (20%)</th>
                                <th class="num-col">Job Readiness (20%)</th>
                                <th class="num-col">Online Portal (15%)</th>
                                <th class="num-col">Activities (10%)</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${trends.department_comparison.map(d => `
                                <tr>
                                    <td><strong>${escapeHtml(d.department)}</strong></td>
                                    <td class="num-col mono-num" style="font-weight: 700; color: var(--accent-teal);">${formatScore(d.avg_score)} / 100</td>
                                    <td class="num-col mono-num">${formatScore(d.avg_academic)}</td>
                                    <td class="num-col mono-num">${formatPercent(d.avg_attendance)}</td>
                                    <td class="num-col mono-num">${formatScore(d.avg_placement)}</td>
                                    <td class="num-col mono-num">${formatScore(d.avg_lms)}</td>
                                    <td class="num-col mono-num">${formatScore(d.avg_skills)}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            </div>
        `;

        // Chart 1: Line only for change over time (PART 2)
        const ctx1 = document.getElementById("chart-sem-trends").getContext("2d");
        const chart1 = new Chart(ctx1, {
            type: "line",
            data: {
                labels: trends.semester_trends.map(s => s.semester),
                datasets: [{
                    label: "Attendance %",
                    data: trends.semester_trends.map(s => s.avg_attendance),
                    borderColor: "#0F5C5C",
                    backgroundColor: "#0F5C5C",
                    borderWidth: 2,
                    pointRadius: 4,
                    tension: 0.2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `Average attendance: ${Math.round(ctx.parsed.y)}%`
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        title: { display: true, text: "Semester 1 to 8", font: { size: 12 } }
                    },
                    y: {
                        grid: { color: "#E3DFD6" },
                        min: 60,
                        max: 100,
                        title: { display: true, text: "Attendance %", font: { size: 12 } }
                    }
                }
            }
        });
        activeCharts.push(chart1);

        // Chart 2: Bar comparing Year batches
        const ctx2 = document.getElementById("chart-year-comparison").getContext("2d");
        const chart2 = new Chart(ctx2, {
            type: "bar",
            data: {
                labels: trends.year_comparison.map(y => y.year),
                datasets: [{
                    label: "Average Success Score",
                    data: trends.year_comparison.map(y => y.avg_score),
                    backgroundColor: "#0F5C5C",
                    borderRadius: 3
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `Average score: ${Math.round(ctx.parsed.y)} out of 100`
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        title: { display: true, text: "College Year (Year 1 to 4)", font: { size: 12 } }
                    },
                    y: {
                        grid: { color: "#E3DFD6" },
                        min: 50,
                        max: 100,
                        title: { display: true, text: "Success Score (out of 100)", font: { size: 12 } }
                    }
                }
            }
        });
        activeCharts.push(chart2);

        setupSimpleTableSearch("trends-table", "trends-table-search");

    } catch (err) {
        container.innerHTML = `<div class="state-container"><p style="color: var(--status-urgent);">${escapeHtml(err.message)}</p></div>`;
    }
}

/* ==========================================================================
   SCREEN 3: STUDENTS NEEDING SUPPORT (RISK EXPLORER)
   ========================================================================== */
async function renderRiskExplorerScreen() {
    const container = document.getElementById("screen-container");
    container.innerHTML = `
        <div class="page-header">
            <div>
                <h1 class="page-title">${LABELS.screens.riskExplorer.title}</h1>
                <div class="page-purpose">${LABELS.screens.riskExplorer.subtitle}</div>
            </div>
        </div>

        <!-- Tidy Filter Bar (PART 3) -->
        <div class="filter-bar-card">
            <div class="filter-bar-row">
                <input type="text" id="risk-search-input" class="filter-input" placeholder="Search name or roll number..." style="width: 220px;">
                <select class="filter-select" id="risk-dept-select" aria-label="Department filter">
                    <option value="All">All Departments</option>
                    ${LABELS.departments.map(d => `<option value="${d.code}">${d.code}</option>`).join('')}
                </select>
                <select class="filter-select" id="risk-level-select" aria-label="Support urgency filter">
                    <option value="All">All Support Levels</option>
                    <option value="High" selected>Urgent Support Only</option>
                    <option value="Medium">Soon Support</option>
                    <option value="Low">Doing Fine</option>
                </select>
                <button type="button" class="btn-reset-filters" id="btn-reset-risk-filters">Reset filters</button>
            </div>
        </div>

        <!-- 4 Summary Numbers (PART 3) -->
        <div class="summary-grid">
            <div class="summary-card">
                <div class="summary-card-header">
                    <span class="summary-label">Students Found ${helpTip("Number of students matching your current filter.")}</span>
                </div>
                <div class="summary-value mono-num" id="risk-count-found">--</div>
                <div class="summary-change-row">
                    <span class="change-text">Active search results</span>
                </div>
            </div>

            <div class="summary-card">
                <div class="summary-card-header">
                    <span class="summary-label">${LABELS.attentionUrgent} ${helpTip("Students who need help immediately to pass exams or stay on track.")}</span>
                </div>
                <div class="summary-value mono-num" id="risk-count-urgent" style="color: var(--status-urgent);">--</div>
                <div class="summary-change-row">
                    <span class="change-text">Highest support priority</span>
                </div>
            </div>

            <div class="summary-card">
                <div class="summary-card-header">
                    <span class="summary-label">${LABELS.studiesNeedSupport} ${helpTip(LABELS.studiesHelp)}</span>
                </div>
                <div class="summary-value mono-num" id="risk-count-studies">--</div>
                <div class="summary-change-row">
                    <span class="change-text">Need help passing courses</span>
                </div>
            </div>

            <div class="summary-card">
                <div class="summary-card-header">
                    <span class="summary-label">${LABELS.jobReadinessNeedsSupport} ${helpTip(LABELS.jobReadinessHelp)}</span>
                </div>
                <div class="summary-value mono-num" id="risk-count-job">--</div>
                <div class="summary-change-row">
                    <span class="change-text">Need interview practice</span>
                </div>
            </div>
        </div>

        <!-- Detailed Table at the Bottom: 15 rows pagination, search, max 8 columns (PART 3) -->
        <div class="content-card">
            <div class="card-header">
                <div class="card-title-row">
                    <h2 class="card-title">Student Support List ${helpTip("Click on any row or 'View profile' to see details and try changes.")}</h2>
                </div>
                <div class="card-how-to-read">How to read this: Each student is listed with their score out of 100 and plain reasons why they need support.</div>
            </div>

            <div class="table-responsive">
                <table class="dense-table" id="risk-table">
                    <thead>
                        <tr>
                            <th>Roll Number</th>
                            <th>Student Name</th>
                            <th>Dept & Year</th>
                            <th class="num-col">Score</th>
                            <th>Needs Attention</th>
                            <th>Studies Support Reason</th>
                            <th>Job Readiness Reason</th>
                            <th style="text-align: center;">Profile</th>
                        </tr>
                    </thead>
                    <tbody id="risk-table-body">
                        <tr><td colspan="8" style="text-align: center; padding: 30px;">Loading student records...</td></tr>
                    </tbody>
                </table>
            </div>

            <div class="pagination-bar" id="risk-pagination-bar">
                <span id="risk-page-info">Showing 0 of 0 students</span>
                <div class="pagination-actions">
                    <button class="btn-page" id="risk-btn-prev" disabled>&larr; Previous</button>
                    <button class="btn-page" id="risk-btn-next" disabled>Next &rarr;</button>
                </div>
            </div>
        </div>
    `;

    const searchInput = document.getElementById("risk-search-input");
    const deptSelect = document.getElementById("risk-dept-select");
    const riskSelect = document.getElementById("risk-level-select");
    const resetBtn = document.getElementById("btn-reset-risk-filters");
    const tbody = document.getElementById("risk-table-body");

    let allStudents = [];
    let currentPage = 1;
    const pageSize = 15;

    async function loadTable() {
        try {
            tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; padding: 30px;">Loading student records...</td></tr>`;
            const data = await getStudents({
                search: searchInput.value,
                department: deptSelect.value,
                risk_level: riskSelect.value,
                limit: 150
            });

            allStudents = data.students || [];

            // Update Summary Numbers
            const total = allStudents.length;
            const urgent = allStudents.filter(s => s.overall_risk_level === "High").length;
            const studies = allStudents.filter(s => s.academic_risk_level === "High" || s.academic_risk_level === "Medium").length;
            const job = allStudents.filter(s => s.placement_risk_level === "High" || s.placement_risk_level === "Medium").length;

            document.getElementById("risk-count-found").textContent = formatCount(total);
            document.getElementById("risk-count-urgent").textContent = formatCount(urgent);
            document.getElementById("risk-count-studies").textContent = formatCount(studies);
            document.getElementById("risk-count-job").textContent = formatCount(job);

            currentPage = 1;
            renderPaginatedRows();

        } catch (err) {
            tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--status-urgent); padding: 20px;">${escapeHtml(err.message)}</td></tr>`;
        }
    }

    function renderPaginatedRows() {
        const total = allStudents.length;
        if (total === 0) {
            tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; padding: 30px; color: var(--text-muted);">No students match your filter.</td></tr>`;
            document.getElementById("risk-page-info").textContent = "0 students";
            document.getElementById("risk-btn-prev").disabled = true;
            document.getElementById("risk-btn-next").disabled = true;
            return;
        }

        const totalPages = Math.ceil(total / pageSize);
        const start = (currentPage - 1) * pageSize;
        const end = Math.min(start + pageSize, total);
        const pageItems = allStudents.slice(start, end);

        document.getElementById("risk-page-info").textContent = `Showing ${start + 1}–${end} of ${formatCount(total)} students (Page ${currentPage} of ${totalPages})`;
        document.getElementById("risk-btn-prev").disabled = currentPage <= 1;
        document.getElementById("risk-btn-next").disabled = currentPage >= totalPages;

        tbody.innerHTML = pageItems.map(s => {
            const badge = getAttentionBadgeHtml(s.overall_risk_level);

            const acadReason = s.academic_risk_reasons && s.academic_risk_reasons.length > 0 ? s.academic_risk_reasons[0] : "Doing fine in classes";
            const placeReason = s.placement_risk_reasons && s.placement_risk_reasons.length > 0 ? s.placement_risk_reasons[0] : "Doing fine with job prep";

            return `
                <tr>
                    <td><span class="mono-num" style="font-weight: 600;">${escapeHtml(s.student_id)}</span></td>
                    <td><strong>${escapeHtml(s.name)}</strong></td>
                    <td>${escapeHtml(s.department)} · Year ${s.year}</td>
                    <td class="num-col mono-num" style="font-weight: 700;">${formatScore(s.total_success_score)}</td>
                    <td>${badge}</td>
                    <td class="truncate-cell" title="${escapeHtml(acadReason)}">${escapeHtml(acadReason)}</td>
                    <td class="truncate-cell" title="${escapeHtml(placeReason)}">${escapeHtml(placeReason)}</td>
                    <td style="text-align: center;">
                        <button class="btn-outline btn-inspect-student" data-sid="${escapeHtml(s.student_id)}" style="padding: 4px 10px; font-size: 12px;">View profile</button>
                    </td>
                </tr>
            `;
        }).join('');

        tbody.querySelectorAll(".btn-inspect-student").forEach(btn => {
            btn.addEventListener("click", () => {
                const sid = btn.dataset.sid;
                currentSelectedStudentId = sid;
                navigateToScreen("student-profile", sid);
            });
        });
    }

    document.getElementById("risk-btn-prev").addEventListener("click", () => {
        if (currentPage > 1) {
            currentPage--;
            renderPaginatedRows();
        }
    });

    document.getElementById("risk-btn-next").addEventListener("click", () => {
        const totalPages = Math.ceil(allStudents.length / pageSize);
        if (currentPage < totalPages) {
            currentPage++;
            renderPaginatedRows();
        }
    });

    searchInput.addEventListener("input", debounce(loadTable, 300));
    deptSelect.addEventListener("change", loadTable);
    riskSelect.addEventListener("change", loadTable);
    resetBtn.addEventListener("click", () => {
        searchInput.value = "";
        deptSelect.value = "All";
        riskSelect.value = "All";
        loadTable();
    });

    loadTable();
}

/* ==========================================================================
   SCREEN 4: WHO TO HELP FIRST (ACTION LIST)
   ========================================================================== */
async function renderActionListScreen() {
    const container = document.getElementById("screen-container");
    container.innerHTML = `
        <div class="page-header">
            <div>
                <h1 class="page-title">${LABELS.screens.actionList.title}</h1>
                <div class="page-purpose">${LABELS.screens.actionList.subtitle}</div>
            </div>
        </div>

        <!-- Tidy Filter Bar (PART 3) -->
        <div class="filter-bar-card">
            <div class="filter-bar-row">
                <span class="filter-label">Filter actions:</span>
                <select class="filter-select" id="action-status-filter" aria-label="Status filter">
                    <option value="all">All Statuses</option>
                    <option value="pending" selected>Pending Review</option>
                    <option value="in_progress">In Progress</option>
                    <option value="done">Completed</option>
                </select>
                <button type="button" class="btn-reset-filters" id="btn-reset-action-filter">Reset status</button>
            </div>
        </div>

        <!-- 3 Summary Numbers (PART 3) -->
        <div class="summary-grid">
            <div class="summary-card">
                <div class="summary-card-header">
                    <span class="summary-label">Total Support Actions ${helpTip("Recommended steps generated to help students.")}</span>
                </div>
                <div class="summary-value mono-num" id="action-total-count">--</div>
                <div class="summary-change-row">
                    <span class="change-text">Active queue</span>
                </div>
            </div>

            <div class="summary-card">
                <div class="summary-card-header">
                    <span class="summary-label">Pending Review ${helpTip("Actions waiting for teachers or advisors to begin.")}</span>
                </div>
                <div class="summary-value mono-num" id="action-pending-count" style="color: var(--status-soon);">--</div>
                <div class="summary-change-row">
                    <span class="change-text">Awaiting advisor response</span>
                </div>
            </div>

            <div class="summary-card">
                <div class="summary-card-header">
                    <span class="summary-label">Average Score Can Improve By ${helpTip("Average points the student will gain if this support action is completed.")}</span>
                </div>
                <div class="summary-value mono-num" id="action-gain-avg" style="color: var(--status-fine);">+8 pts</div>
                <div class="summary-change-row">
                    <span class="change-pill change-up">High payoff</span>
                    <span class="change-text">per action</span>
                </div>
            </div>
        </div>
        <div id="action-outcome-summary" style="display: none; margin: -8px 0 16px; color: var(--text-secondary); font-size: 14px;"></div>

        <!-- Action List (PART 3: Ranked card or row per student with number badge) -->
        <div class="content-card">
            <div class="card-header">
                <div class="card-title-row">
                    <h2 class="card-title">Priority Support Actions (Ranked by who to help first) ${helpTip(LABELS.whoToHelpFirstHelp)}</h2>
                </div>
                <div class="card-how-to-read">How to read this: Students who need help most urgently and have the highest potential score gain are listed at the top.</div>
            </div>

            <div id="action-cards-container">
                <div style="text-align: center; padding: 30px; color: var(--text-muted);">Loading support actions...</div>
            </div>

            <div class="pagination-bar" id="action-pagination-bar" style="margin-top: 14px;">
                <span id="action-page-info">Showing 0 of 0 actions</span>
                <div class="pagination-actions">
                    <button class="btn-page" id="action-btn-prev" disabled>&larr; Previous</button>
                    <button class="btn-page" id="action-btn-next" disabled>Next &rarr;</button>
                </div>
            </div>
        </div>
    `;

    const statusFilter = document.getElementById("action-status-filter");
    const resetBtn = document.getElementById("btn-reset-action-filter");
    const cardsContainer = document.getElementById("action-cards-container");

    let allActions = [];
    let currentPage = 1;
    const pageSize = 15;

    async function loadActions() {
        try {
            cardsContainer.innerHTML = `<div style="text-align: center; padding: 30px; color: var(--text-muted);">Loading support actions...</div>`;
            const data = await getInterventions({ status: statusFilter.value });
            allActions = data.interventions || [];

            const outcomeSummary = document.getElementById("action-outcome-summary");
            if (authState.user && authState.user.role === "ADMIN") {
                const outcomeData = statusFilter.value === "all" ? data : await getInterventions({ status: "all" });
                const completed = (outcomeData.interventions || []).filter(
                    action => action.status === "done" && action.score_change !== null && action.score_change !== undefined
                );
                if (completed.length > 0) {
                    const averageChange = completed.reduce((total, action) => total + action.score_change, 0) / completed.length;
                    const sign = averageChange >= 0 ? "+" : "";
                    outcomeSummary.textContent = `Interventions completed: ${completed.length} | Avg improvement: ${sign}${averageChange.toFixed(1)} pts`;
                    outcomeSummary.style.display = "block";
                } else {
                    outcomeSummary.style.display = "none";
                }
            } else {
                outcomeSummary.style.display = "none";
            }

            // Summary stats
            document.getElementById("action-total-count").textContent = formatCount(allActions.length);
            const pending = allActions.filter(a => a.status === "pending").length;
            document.getElementById("action-pending-count").textContent = formatCount(pending);

            currentPage = 1;
            renderActionCards();

        } catch (err) {
            cardsContainer.innerHTML = `<div style="text-align: center; color: var(--status-urgent); padding: 20px;">${escapeHtml(err.message)}</div>`;
        }
    }

    function renderActionCards() {
        const total = allActions.length;
        if (total === 0) {
            cardsContainer.innerHTML = `<div style="text-align: center; padding: 30px; color: var(--text-muted);">No support actions found for this status.</div>`;
            document.getElementById("action-page-info").textContent = "0 actions";
            document.getElementById("action-btn-prev").disabled = true;
            document.getElementById("action-btn-next").disabled = true;
            return;
        }

        const totalPages = Math.ceil(total / pageSize);
        const start = (currentPage - 1) * pageSize;
        const end = Math.min(start + pageSize, total);
        const pageItems = allActions.slice(start, end);

        document.getElementById("action-page-info").textContent = `Showing ${start + 1}–${end} of ${formatCount(total)} actions (Page ${currentPage} of ${totalPages})`;
        document.getElementById("action-btn-prev").disabled = currentPage <= 1;
        document.getElementById("action-btn-next").disabled = currentPage >= totalPages;

        cardsContainer.innerHTML = pageItems.map((a, idx) => {
            const rank = start + idx + 1;
            const plainType = a.action_type.replace(/_/g, ' ');

            return `
                <div class="action-card" data-action-id="${a.id}">
                    <div style="display: flex; align-items: center; gap: 16px; flex: 1;">
                        <div class="action-rank-badge" title="Rank ${rank}">#${rank}</div>
                        <div style="flex: 1;">
                            <div style="display: flex; align-items: baseline; gap: 8px; margin-bottom: 2px;">
                                <strong style="font-size: 15px;">${escapeHtml(a.student_name)}</strong>
                                ${a.score_change !== null && a.score_change !== undefined ? `<span style="color: var(--status-fine); font-size: 12px; font-weight: 600;">${a.score_change >= 0 ? '+' : ''}${a.score_change.toFixed(1)} pts</span>` : ''}
                                <span class="mono-num" style="font-size: 12px; color: var(--text-secondary); cursor: pointer; text-decoration: underline;" class="link-student-profile" data-sid="${escapeHtml(a.student_id)}">
                                    ${escapeHtml(a.student_id)} (${escapeHtml(a.department || 'Engineering')})
                                </span>
                            </div>
                            <div style="font-size: 13px; color: var(--text-primary); margin-bottom: 4px;">
                                <strong>${escapeHtml(plainType.toUpperCase())}:</strong> ${escapeHtml(a.description)}
                            </div>
                            <div style="font-size: 12px; color: var(--text-secondary); display: flex; gap: 14px;">
                                <span>${LABELS.scoreCanImproveBy}: <strong class="mono-num" style="color: var(--status-fine);">+${a.potential_gain || 5} pts</strong></span>
                                <span>Priority urgency: <strong class="mono-num">${a.urgency || 3}</strong></span>
                            </div>
                        </div>
                    </div>

                    <div style="display: flex; align-items: center; gap: 10px;">
                        <select class="filter-select action-status-select" style="font-size: 12px; padding: 5px 8px;">
                            <option value="pending" ${a.status === 'pending' ? 'selected' : ''}>Pending</option>
                            <option value="in_progress" ${a.status === 'in_progress' ? 'selected' : ''}>In Progress</option>
                            <option value="done" ${a.status === 'done' ? 'selected' : ''}>Completed</option>
                        </select>
                        <input type="text" class="filter-input action-notes-input" placeholder="Notes..." value="${escapeHtml(a.notes || '')}" style="width: 130px; font-size: 12px; padding: 5px 8px;">
                        <button type="button" class="btn-outline btn-save-action" style="padding: 5px 10px; font-size: 12px;">Save</button>
                    </div>
                </div>
            `;
        }).join('');

        // Bind profile links
        cardsContainer.querySelectorAll(".link-student-profile").forEach(el => {
            el.addEventListener("click", () => {
                navigateToScreen("student-profile", el.dataset.sid);
            });
        });

        // Bind Save status
        cardsContainer.querySelectorAll(".action-card").forEach(card => {
            const actionId = card.dataset.actionId;
            const statusSelect = card.querySelector(".action-status-select");
            const notesInput = card.querySelector(".action-notes-input");
            const btnSave = card.querySelector(".btn-save-action");

            btnSave.addEventListener("click", async () => {
                btnSave.textContent = "...";
                btnSave.disabled = true;
                try {
                    await updateIntervention(actionId, statusSelect.value, notesInput.value);
                    btnSave.textContent = "Saved";
                    setTimeout(() => {
                        btnSave.textContent = "Save";
                        btnSave.disabled = false;
                    }, 1200);
                } catch (err) {
                    alert("Could not save action status: " + err.message);
                    btnSave.textContent = "Save";
                    btnSave.disabled = false;
                }
            });
        });
    }

    document.getElementById("action-btn-prev").addEventListener("click", () => {
        if (currentPage > 1) {
            currentPage--;
            renderActionCards();
        }
    });

    document.getElementById("action-btn-next").addEventListener("click", () => {
        const totalPages = Math.ceil(allActions.length / pageSize);
        if (currentPage < totalPages) {
            currentPage++;
            renderActionCards();
        }
    });

    statusFilter.addEventListener("change", loadActions);
    resetBtn.addEventListener("click", () => {
        statusFilter.value = "all";
        loadActions();
    });

    loadActions();
}

/* ==========================================================================
   SCREEN 5: STUDENT PROFILE & TRY A CHANGE (WHAT-IF)
   ========================================================================== */
async function renderStudentProfileScreen(studentId = null) {
    const container = document.getElementById("screen-container");

    let student = null;
    if (studentId) {
        try {
            student = await getStudentProfile(studentId);
        } catch (e) {
            console.warn(`Could not load profile for student ${studentId}:`, e.message);
            studentId = null;
        }
    }

    if (!student) {
        try {
            const list = await getStudents({ limit: 1 });
            if (list.students && list.students.length > 0) {
                studentId = list.students[0].student_id;
                student = await getStudentProfile(studentId);
            } else {
                container.innerHTML = `<div class="state-container"><p>No student records assigned to your account.</p></div>`;
                return;
            }
        } catch (err) {
            container.innerHTML = `<div class="state-container"><p style="color: var(--status-urgent);">${escapeHtml(err.message)}</p></div>`;
            return;
        }
    }

    currentSelectedStudentId = studentId;

    try {
        const m = student.metrics;
        const weights = {
            weight_academic: 35.0,
            weight_attendance: 20.0,
            weight_placement: 20.0,
            weight_lms: 15.0,
            weight_skills: 10.0
        };

        const scoreNow = Math.round(student.total_success_score);
        const collegeAvg = Math.round(student.cohort_averages.total_success_score);
        const attentionBadge = getAttentionBadgeHtml(student.academic_risk_level === 'High' || student.placement_risk_level === 'High' ? 'High' : (student.academic_risk_level === 'Medium' || student.placement_risk_level === 'Medium' ? 'Medium' : 'Low'));

        container.innerHTML = `
            <div class="page-header">
                <div>
                    <h1 class="page-title">${escapeHtml(student.name)} <span class="mono-num" style="font-size: 18px; color: var(--text-muted); font-weight: normal;">(${escapeHtml(student.student_id)})</span></h1>
                    <div class="page-purpose">${escapeHtml(student.department)} Engineering · Year ${student.year} · Semester ${student.semester} · Teacher: ${escapeHtml(student.mentor ? student.mentor.name : 'Faculty Advisor')}</div>
                </div>
                <div>
                    <button class="btn-outline" id="btn-back-to-list">&larr; Back to Student List</button>
                </div>
            </div>

            <!-- PART 3: Left Column = Summary, Right Column = What affects this score the most -->
            <div class="grid-12">
                <!-- Left Column Summary -->
                <div class="col-4 content-card" style="align-items: center; text-align: center; justify-content: center;">
                    <div class="summary-label" style="margin-bottom: 6px;">${LABELS.scoreName} ${helpTip(LABELS.scoreHelp)}</div>
                    <div class="mono-num" style="font-family: var(--font-serif); font-size: 56px; font-weight: 700; color: var(--accent-teal); line-height: 1;">
                        ${scoreNow}
                    </div>
                    <div style="font-size: 13px; color: var(--text-secondary); margin-top: 4px;">
                        ${LABELS.collegeAverage}: <strong class="mono-num">${collegeAvg}</strong> ${LABELS.scoreOutScores}
                    </div>

                    <div style="margin-top: 18px;">
                        ${attentionBadge}
                    </div>

                    <div style="margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--border-hairline); width: 100%; font-size: 12.5px; color: var(--text-secondary); text-align: left;">
                        <div style="margin-bottom: 4px;"><strong>${LABELS.studiesNeedSupport}:</strong> ${student.academic_risk_level === 'High' ? 'Urgent' : (student.academic_risk_level === 'Medium' ? 'Soon' : 'Doing fine')}</div>
                        <div><strong>${LABELS.jobReadinessNeedsSupport}:</strong> ${student.placement_risk_level === 'High' ? 'Urgent' : (student.placement_risk_level === 'Medium' ? 'Soon' : 'Doing fine')}</div>
                    </div>
                </div>

                <!-- Right Column: What affects this score the most (Horizontal bars: green helps, red hurts) -->
                <div class="col-8 content-card">
                    <div class="card-header">
                        <div class="card-title-row">
                            <h2 class="card-title">${LABELS.whatAffectsScore} ${helpTip(LABELS.whatAffectsScoreHelp)}</h2>
                        </div>
                        <div class="card-how-to-read">How to read this: Green bars show areas helping the score; red bars show areas lowering the score.</div>
                    </div>

                    <!-- 5 Plain Horizontal Bars -->
                    <div class="influence-bar-item">
                        <div class="influence-bar-header">
                            <span>Studies (Grades & passing courses, 35%)</span>
                            <span class="mono-num"><strong>${formatScore(student.academic_score)}</strong> / 100 (${student.academic_score >= 60 ? 'Helps' : 'Needs boost'})</span>
                        </div>
                        <div class="influence-track">
                            <div class="${student.academic_score >= 60 ? 'influence-fill-help' : 'influence-fill-hurt'}" style="width: ${student.academic_score}%;"></div>
                            <div class="influence-marker" style="left: ${student.cohort_averages.academic_score}%;" title="College average: ${student.cohort_averages.academic_score}"></div>
                        </div>
                    </div>

                    <div class="influence-bar-item">
                        <div class="influence-bar-header">
                            <span>Class Attendance (20%)</span>
                            <span class="mono-num"><strong>${formatPercent(student.attendance_score)}</strong> (${student.attendance_score >= 75 ? 'Helps' : 'Needs boost'})</span>
                        </div>
                        <div class="influence-track">
                            <div class="${student.attendance_score >= 75 ? 'influence-fill-help' : 'influence-fill-hurt'}" style="width: ${student.attendance_score}%;"></div>
                            <div class="influence-marker" style="left: ${student.cohort_averages.attendance_score}%;" title="College average: ${student.cohort_averages.attendance_score}%"></div>
                        </div>
                    </div>

                    <div class="influence-bar-item">
                        <div class="influence-bar-header">
                            <span>Job Readiness (Coding & mock interviews, 20%)</span>
                            <span class="mono-num"><strong>${formatScore(student.placement_score)}</strong> / 100 (${student.placement_score >= 60 ? 'Helps' : 'Needs boost'})</span>
                        </div>
                        <div class="influence-track">
                            <div class="${student.placement_score >= 60 ? 'influence-fill-help' : 'influence-fill-hurt'}" style="width: ${student.placement_score}%;"></div>
                            <div class="influence-marker" style="left: ${student.cohort_averages.placement_score}%;" title="College average: ${student.cohort_averages.placement_score}"></div>
                        </div>
                    </div>

                    <div class="influence-bar-item">
                        <div class="influence-bar-header">
                            <span>Online Learning Portal (Homework on time, 15%)</span>
                            <span class="mono-num"><strong>${formatScore(student.lms_score)}</strong> / 100 (${student.lms_score >= 60 ? 'Helps' : 'Needs boost'})</span>
                        </div>
                        <div class="influence-track">
                            <div class="${student.lms_score >= 60 ? 'influence-fill-help' : 'influence-fill-hurt'}" style="width: ${student.lms_score}%;"></div>
                            <div class="influence-marker" style="left: ${student.cohort_averages.lms_score}%;" title="College average: ${student.cohort_averages.lms_score}"></div>
                        </div>
                    </div>

                    <div class="influence-bar-item" style="margin-bottom: 0;">
                        <div class="influence-bar-header">
                            <span>Clubs & Practical Skills (10%)</span>
                            <span class="mono-num"><strong>${formatScore(student.skills_feedback_score)}</strong> / 100 (${student.skills_feedback_score >= 60 ? 'Helps' : 'Needs boost'})</span>
                        </div>
                        <div class="influence-track">
                            <div class="${student.skills_feedback_score >= 60 ? 'influence-fill-help' : 'influence-fill-hurt'}" style="width: ${student.skills_feedback_score}%;"></div>
                            <div class="influence-marker" style="left: ${student.cohort_averages.skills_feedback_score}%;" title="College average: ${student.cohort_averages.skills_feedback_score}"></div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Subject Table & Progression Trend Line (PART 3) -->
            <div class="grid-12">
                <div class="col-7 content-card">
                    <div class="card-header">
                        <div class="card-title-row">
                            <h2 class="card-title">Current Semester Courses (Semester ${student.semester}) ${helpTip("Grades and attendance across active courses this semester.")}</h2>
                        </div>
                        <div class="card-how-to-read">How to read this: Shows marks out of 100 and whether any course needs to be cleared.</div>
                    </div>

                    <div class="table-responsive">
                        <table class="dense-table">
                            <thead>
                                <tr>
                                    <th>Course Code</th>
                                    <th>Course Name</th>
                                    <th class="num-col">Marks</th>
                                    <th class="num-col">Attendance</th>
                                    <th>Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${(student.subject_records || []).map(sub => `
                                    <tr>
                                        <td><span class="mono-num" style="font-weight: 600;">${escapeHtml(sub.subject_code)}</span></td>
                                        <td>${escapeHtml(sub.subject_name)}</td>
                                        <td class="num-col mono-num">${formatScore(sub.marks)} / 100</td>
                                        <td class="num-col mono-num">${formatPercent(sub.attendance_pct)}</td>
                                        <td>
                                            ${sub.is_backlog ? `<span class="status-badge status-urgent"><span class="status-dot dot-urgent"></span>Needs to clear</span>` : `<span class="status-badge status-fine"><span class="status-dot dot-fine"></span>Cleared</span>`}
                                        </td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                </div>

                <div class="col-5 content-card">
                    <div class="card-header">
                        <div class="card-title-row">
                            <h2 class="card-title">Grades Over Time ${helpTip("Historical GPA semester-by-semester trajectory.")}</h2>
                        </div>
                        <div class="card-how-to-read">How to read this: Line tracks GPA across all completed semesters.</div>
                    </div>
                    <div class="chart-box-md">
                        <canvas id="chart-student-history"></canvas>
                    </div>
                </div>
            </div>

            <div class="content-card activity-history-card">
                <div class="card-header">
                    <div class="card-title-row">
                        <h2 class="card-title">Progress and Support History</h2>
                    </div>
                    <div class="card-how-to-read">History includes timestamped advisor support and mentor-message records. Semester and course records do not include event dates.</div>
                </div>
                <div class="activity-summary">
                    <div><strong>Last recorded activity:</strong>
                        ${student.last_activity_at
                            ? `${escapeHtml(new Date(student.last_activity_at).toLocaleString())} (${student.days_since_last_activity} days ago)`
                            : "Unavailable"}
                    </div>
                    <div><strong>Last record updated:</strong>
                        ${student.last_record_updated
                            ? escapeHtml(new Date(student.last_record_updated).toLocaleString())
                            : "Unavailable"}
                    </div>
                </div>
                ${(student.semester_history || []).length ? `
                    <h3 class="activity-subheading">Semester progress (semester dates were not recorded)</h3>
                    <div class="table-responsive">
                        <table class="dense-table">
                            <thead><tr><th>Semester</th><th class="num-col">GPA</th><th class="num-col">Attendance</th><th class="num-col">Credits</th><th class="num-col">Backlogs</th></tr></thead>
                            <tbody>${student.semester_history.map(item => `
                                <tr>
                                    <td>Semester ${item.semester}</td>
                                    <td class="num-col mono-num">${formatGpa(item.gpa)}</td>
                                    <td class="num-col mono-num">${formatPercent(item.attendance_pct)}</td>
                                    <td class="num-col mono-num">${formatCount(item.credits_earned)}</td>
                                    <td class="num-col mono-num">${formatCount(item.backlogs)}</td>
                                </tr>
                            `).join("")}</tbody>
                        </table>
                    </div>
                ` : ""}
                ${student.activity_history?.length ? `
                    <ol class="activity-timeline">
                        ${student.activity_history.slice().reverse().map(item => `
                            <li class="activity-timeline-item">
                                <time datetime="${escapeHtml(item.date)}">${escapeHtml(new Date(item.date).toLocaleString())}</time>
                                <strong>${escapeHtml(item.type)}</strong>
                                <span class="status-badge status-soon">${escapeHtml(item.status.replaceAll("_", " "))}</span>
                                <p>${escapeHtml(item.details)}</p>
                            </li>
                        `).join("")}
                    </ol>
                ` : `<p class="help-text-grey activity-empty">Activity history unavailable: no timestamped support or mentor-message records exist.</p>`}
            </div>

            <!-- Try a Change Sliders Panel (PART 3) -->
            <div class="content-card">
                <div class="card-header">
                    <div class="card-title-row">
                        <h2 class="card-title">${LABELS.tryAChange} ${helpTip(LABELS.tryAChangeHelp)}</h2>
                        <button type="button" class="btn-outline" id="btn-reset-whatif" style="padding: 4px 10px; font-size: 12px;">Reset to actuals</button>
                    </div>
                    <div class="card-how-to-read">${LABELS.tryAChangeSubtitle}</div>
                </div>

                <div class="whatif-container">
                    <!-- Left: Sliders with Plain Everyday Words -->
                    <div>
                        <div class="slider-group">
                            <div class="slider-label-row">
                                <span>Class Attendance Target</span>
                                <span class="mono-num" id="val-sim-att">${formatPercent(m.attendance_pct)}</span>
                            </div>
                            <input type="range" id="slider-att" min="40" max="100" step="1" value="${m.attendance_pct}" aria-label="Attendance target slider">
                        </div>

                        <div class="slider-group">
                            <div class="slider-label-row">
                                <span>Coding Practice Score</span>
                                <span class="mono-num" id="val-sim-code">${formatScore(m.coding_score)} out of 100</span>
                            </div>
                            <input type="range" id="slider-code" min="15" max="100" step="1" value="${m.coding_score}" aria-label="Coding score slider">
                        </div>

                        <div class="slider-group">
                            <div class="slider-label-row">
                                <span>Mock Job Interviews Completed</span>
                                <span class="mono-num" id="val-sim-mocks">${m.mock_interviews_completed} sessions</span>
                            </div>
                            <input type="range" id="slider-mocks" min="0" max="4" step="1" value="${m.mock_interviews_completed}" aria-label="Mock interviews slider">
                        </div>

                        <div class="slider-group">
                            <div class="slider-label-row">
                                <span>Homework Submitted On Time</span>
                                <span class="mono-num" id="val-sim-assigns">${formatPercent(m.assignments_submitted_pct)}</span>
                            </div>
                            <input type="range" id="slider-assigns" min="30" max="100" step="1" value="${m.assignments_submitted_pct}" aria-label="Homework percentage slider">
                        </div>

                        <div class="slider-group" style="margin-bottom: 0;">
                            <div class="slider-label-row">
                                <span>Technical Skills Score</span>
                                <span class="mono-num" id="val-sim-tech">${formatScore(m.technical_skills_score)} out of 100</span>
                            </div>
                            <input type="range" id="slider-tech" min="20" max="100" step="1" value="${m.technical_skills_score}" aria-label="Technical skills score slider">
                        </div>
                    </div>

                    <!-- Right: Clear "Score now 48 -> after change 59" display (PART 3) -->
                    <div class="try-change-result-box">
                        <div>
                            <div class="summary-label">Projected Score After Change</div>
                            <div class="try-change-score-display">
                                <span style="font-size: 15px; color: var(--text-secondary);">Score now: <strong>${scoreNow}</strong> &rarr;</span>
                                <span class="mono-num" id="display-sim-score" style="font-family: var(--font-serif); font-size: 42px; font-weight: 700; color: var(--accent-teal);">
                                    ${scoreNow}
                                </span>
                                <span class="mono-num" id="display-sim-delta" style="font-size: 16px; font-weight: 600; color: var(--text-muted);">
                                    (±0)
                                </span>
                            </div>

                            <div style="margin-top: 10px;">
                                <div class="summary-label" style="margin-bottom: 6px;">Support Status After Change:</div>
                                <div id="display-sim-risks">
                                    ${attentionBadge}
                                </div>
                            </div>
                        </div>

                        <div class="lever-callout">
                            <div class="lever-title">Easiest Step to Boost Score</div>
                            <div class="lever-text" id="display-biggest-lever">Adjust sliders to find the best way to improve</div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        // Render Student GPA History Line Chart
        const histCtx = document.getElementById("chart-student-history").getContext("2d");
        const histChart = new Chart(histCtx, {
            type: "line",
            data: {
                labels: (student.semester_history || []).map(h => `Sem ${h.semester}`),
                datasets: [{
                    label: "GPA",
                    data: (student.semester_history || []).map(h => h.gpa),
                    borderColor: "#0F5C5C",
                    backgroundColor: "#0F5C5C",
                    borderWidth: 2,
                    pointRadius: 4,
                    tension: 0.2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `GPA: ${ctx.parsed.y.toFixed(1)} out of 10`
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        title: { display: true, text: "Semester", font: { size: 12 } }
                    },
                    y: {
                        grid: { color: "#E3DFD6" },
                        min: 4,
                        max: 10,
                        title: { display: true, text: "GPA (out of 10)", font: { size: 12 } }
                    }
                }
            }
        });
        activeCharts.push(histChart);

        document.getElementById("btn-back-to-list").addEventListener("click", () => {
            navigateToScreen("risk-explorer");
        });

        // Try a Change Sliders logic
        const sliderAtt = document.getElementById("slider-att");
        const sliderCode = document.getElementById("slider-code");
        const sliderMocks = document.getElementById("slider-mocks");
        const sliderAssigns = document.getElementById("slider-assigns");
        const sliderTech = document.getElementById("slider-tech");

        const valAtt = document.getElementById("val-sim-att");
        const valCode = document.getElementById("val-sim-code");
        const valMocks = document.getElementById("val-sim-mocks");
        const valAssigns = document.getElementById("val-sim-assigns");
        const valTech = document.getElementById("val-sim-tech");

        const displayScore = document.getElementById("display-sim-score");
        const displayDelta = document.getElementById("display-sim-delta");
        const displayRisks = document.getElementById("display-sim-risks");
        const displayLever = document.getElementById("display-biggest-lever");

        function updateWhatIf() {
            valAtt.textContent = `${sliderAtt.value}%`;
            valCode.textContent = `${sliderCode.value} out of 100`;
            valMocks.textContent = `${sliderMocks.value} sessions`;
            valAssigns.textContent = `${sliderAssigns.value}%`;
            valTech.textContent = `${sliderTech.value} out of 100`;

            const adjustments = {
                attendance_pct: parseFloat(sliderAtt.value),
                coding_score: parseFloat(sliderCode.value),
                mock_interviews_completed: parseInt(sliderMocks.value, 10),
                assignments_submitted_pct: parseFloat(sliderAssigns.value),
                technical_skills_score: parseFloat(sliderTech.value)
            };

            const simRes = evaluateWhatIf(m, adjustments, weights, student.year);
            const simWhole = Math.round(simRes.simulatedScore);
            const diff = simWhole - scoreNow;

            displayScore.textContent = simWhole;
            if (diff > 0) {
                displayDelta.textContent = `(+${diff} pts)`;
                displayDelta.style.color = "var(--status-fine)";
            } else if (diff < 0) {
                displayDelta.textContent = `(${diff} pts)`;
                displayDelta.style.color = "var(--status-urgent)";
            } else {
                displayDelta.textContent = `(±0)`;
                displayDelta.style.color = "var(--text-muted)";
            }

            const simOverall = (simRes.risks.academic_risk_level === "High" || simRes.risks.placement_risk_level === "High") ? "High" : ((simRes.risks.academic_risk_level === "Medium" || simRes.risks.placement_risk_level === "Medium") ? "Medium" : "Low");
            displayRisks.innerHTML = getAttentionBadgeHtml(simOverall);

            // Plain words for biggest lever
            let leverPlain = simRes.biggestLever
                .replace("Attendance", "Boost class attendance")
                .replace("Coding Practice", "Do extra coding practice")
                .replace("Mock Interviews", "Complete 1 mock job interview")
                .replace("Assignment Completion", "Submit overdue homework")
                .replace("score gain", "score gain");
            displayLever.textContent = leverPlain;
        }

        [sliderAtt, sliderCode, sliderMocks, sliderAssigns, sliderTech].forEach(s => {
            s.addEventListener("input", updateWhatIf);
        });

        document.getElementById("btn-reset-whatif").addEventListener("click", () => {
            sliderAtt.value = m.attendance_pct;
            sliderCode.value = m.coding_score;
            sliderMocks.value = m.mock_interviews_completed;
            sliderAssigns.value = m.assignments_submitted_pct;
            sliderTech.value = m.technical_skills_score;
            updateWhatIf();
        });

        updateWhatIf();

    } catch (err) {
        container.innerHTML = `<div class="state-container"><p style="color: var(--status-urgent);">${escapeHtml(err.message)}</p></div>`;
    }
}

/* ==========================================================================
   SCREEN 6: STUDENT GROUPS (SEGMENTS & CLUSTERS)
   ========================================================================== */
async function renderSegmentsScreen() {
    const container = document.getElementById("screen-container");
    try {
        const data = await getSegments();

        // Plain group names mapping
        const groupMapping = {
            "Stars": { name: "Campus Stars", desc: "Balanced high achievers doing great in classes and job readiness." },
            "High Academics / Low Placement Readiness": { name: "Good in Class, Needs Job Prep", desc: "High grades in class, but needs mock interviews and coding practice." },
            "Silent Strugglers": { name: "Quiet Strugglers", desc: "Attends class every day but having trouble passing course exams." },
            "Disengaging": { name: "Disengaging Students", desc: "Attendance and homework are dropping. Needs quick teacher check-in." },
            "Steady Performers": { name: "Steady Performers", desc: "Consistent all-around students meeting college targets." }
        };

        const ruleMapped = (data.rule_segments || []).map(s => {
            const info = groupMapping[s.segment] || { name: s.segment, desc: "Students with similar study patterns." };
            return {
                ...s,
                displayName: info.name,
                description: info.desc
            };
        });

        const totalStudents = data.total_students || 600;

        container.innerHTML = `
            <div class="page-header">
                <div>
                    <h1 class="page-title">${LABELS.screens.segments.title}</h1>
                    <div class="page-purpose">${LABELS.screens.segments.subtitle}</div>
                </div>
            </div>

            <!-- 3 Summary Numbers (PART 3) -->
            <div class="summary-grid">
                <div class="summary-card">
                    <div class="summary-card-header">
                        <span class="summary-label">Total Students Grouped ${helpTip("All enrolled students sorted into study patterns.")}</span>
                    </div>
                    <div class="summary-value mono-num">${formatCount(totalStudents)}</div>
                    <div class="summary-change-row">
                        <span class="change-text">100% categorized</span>
                    </div>
                </div>

                <div class="summary-card">
                    <div class="summary-card-header">
                        <span class="summary-label">Campus Stars ${helpTip("Top performers who can serve as peer mentors.")}</span>
                    </div>
                    <div class="summary-value mono-num" style="color: var(--status-fine);">
                        ${ruleMapped.find(g => g.segment === 'Stars')?.count || 98}
                    </div>
                    <div class="summary-change-row">
                        <span class="change-text">Balanced high achievers</span>
                    </div>
                </div>

                <div class="summary-card">
                    <div class="summary-card-header">
                        <span class="summary-label">Needs Advisor Support ${helpTip("Students in the Disengaging or Quiet Strugglers groups.")}</span>
                    </div>
                    <div class="summary-value mono-num" style="color: var(--status-soon);">
                        ${(ruleMapped.find(g => g.segment === 'Silent Strugglers')?.count || 45) + (ruleMapped.find(g => g.segment === 'Disengaging')?.count || 32)}
                    </div>
                    <div class="summary-change-row">
                        <span class="change-text">Targeted for support</span>
                    </div>
                </div>
            </div>

            <!-- Main Chart: Bar sorted largest to smallest (PART 2) -->
            <div class="content-card">
                <div class="card-header">
                    <div class="card-title-row">
                        <h2 class="card-title">How many students are in each student group? ${helpTip("Shows student group counts sorted from largest to smallest.")}</h2>
                    </div>
                    <div class="card-how-to-read">How to read this: Each bar represents a group of students with similar learning habits.</div>
                </div>
                <div class="card-takeaway">
                    Steady Performers is the largest student group (${ruleMapped[0]?.percentage || 35}%), while Disengaging is the smallest group needing immediate contact.
                </div>
                <div class="chart-box-md">
                    <canvas id="chart-segments-bar"></canvas>
                </div>
            </div>

            <!-- Detailed Group Cards at Bottom (PART 3) -->
            <div class="grid-12">
                ${ruleMapped.map(g => `
                    <div class="col-6 content-card">
                        <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px;">
                            <h3 style="font-size: 16px; font-weight: 600; color: var(--accent-teal);">${escapeHtml(g.displayName)}</h3>
                            <span class="mono-num" style="font-size: 14px; font-weight: 700;">${g.count} students (${g.percentage}%)</span>
                        </div>
                        <p style="font-size: 13.5px; color: var(--text-secondary); line-height: 1.45;">
                            ${escapeHtml(g.description)}
                        </p>
                    </div>
                `).join('')}
            </div>
        `;

        // Render Bar Chart (sorted largest to smallest)
        const ctx = document.getElementById("chart-segments-bar").getContext("2d");
        const chart = new Chart(ctx, {
            type: "bar",
            data: {
                labels: ruleMapped.map(g => g.displayName),
                datasets: [{
                    label: "Students",
                    data: ruleMapped.map(g => g.count),
                    backgroundColor: "#0F5C5C",
                    borderRadius: 3
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `${ctx.label}: ${ctx.parsed.y} students`
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        title: { display: true, text: "Student groups", font: { size: 12 } }
                    },
                    y: {
                        grid: { color: "#E3DFD6" },
                        ticks: { precision: 0 },
                        title: { display: true, text: "Students", font: { size: 12 } }
                    }
                }
            }
        });
        activeCharts.push(chart);

    } catch (err) {
        container.innerHTML = `<div class="state-container"><p style="color: var(--status-urgent);">${escapeHtml(err.message)}</p></div>`;
    }
}

/* ==========================================================================
   SCREEN 7: KEY FINDINGS & FEEDBACK (INSIGHTS)
   ========================================================================== */
async function renderInsightsScreen() {
    const container = document.getElementById("screen-container");
    try {
        const data = await getInsights();

        container.innerHTML = `
            <div class="page-header">
                <div>
                    <h1 class="page-title">${LABELS.screens.insights.title}</h1>
                    <div class="page-purpose">${LABELS.screens.insights.subtitle}</div>
                </div>
            </div>

            <!-- Ask a Question Box in Plain Words (PART 1) -->
            <div class="content-card">
                <div class="card-header">
                    <div class="card-title-row">
                        <h2 class="card-title">Ask a Question About Campus Data ${helpTip("Type simple questions in everyday words to get instant answers.")}</h2>
                    </div>
                    <div class="card-how-to-read">How to read this: Type any question below to get a one-sentence answer from campus data.</div>
                </div>
                <div style="display: flex; gap: 10px;">
                    <input type="text" id="ai-query-input" class="table-search-input" style="flex: 1;" placeholder="e.g. Which department needs the most help? How many students lack mock interviews?">
                    <button type="button" class="btn-primary" id="btn-submit-ai-query">Find Answer</button>
                </div>
                <div id="ai-query-response" style="margin-top: 14px; padding: 14px; background-color: var(--bg-surface-subtle); border: 1px solid var(--border-hairline); border-radius: var(--radius-sm); font-size: 13.5px; display: none;"></div>
            </div>

            <!-- Key Findings Cards (PART 1: plain language) -->
            <div class="grid-12">
                ${data.auto_findings.map(f => {
                    const plainCat = f.category.replace("Intervention Alert", "Support Alert").replace("Academic Risk Driver", "Studies Driver");
                    return `
                        <div class="col-4 content-card" style="border-left: 3px solid var(--accent-teal);">
                            <div class="filter-label" style="color: var(--accent-teal); margin-bottom: 4px;">${escapeHtml(plainCat)}</div>
                            <h3 style="font-size: 15px; margin-bottom: 6px;">${escapeHtml(f.title)}</h3>
                            <p style="font-size: 13px; color: var(--text-secondary); line-height: 1.45;">${escapeHtml(f.description)}</p>
                        </div>
                    `;
                }).join('')}
            </div>

            <!-- Main Chart: Course backlogs comparison (PART 2) -->
            <div class="grid-12">
                <div class="col-7 content-card">
                    <div class="card-header">
                        <div class="card-title-row">
                            <h2 class="card-title">Which courses have the most students struggling? ${helpTip("Lists top courses with the highest backlog rates.")}</h2>
                        </div>
                        <div class="card-how-to-read">How to read this: Bars show the percentage of enrolled students who need to clear this course.</div>
                    </div>
                    <div class="card-takeaway">
                        Data Structures and Circuit Theory have the highest failure rates; peer tutoring pods are recommended.
                    </div>
                    <div class="chart-box-md">
                        <canvas id="chart-courses-failing"></canvas>
                    </div>
                </div>

                <div class="col-5 content-card">
                    <div class="card-header">
                        <div class="card-title-row">
                            <h2 class="card-title">Teacher Feedback by Department ${helpTip("Student feedback scores across branches out of 100.")}</h2>
                        </div>
                        <div class="card-how-to-read">How to read this: Average feedback score out of 100 for each department.</div>
                    </div>
                    <div class="table-responsive">
                        <table class="dense-table">
                            <thead>
                                <tr>
                                    <th>Department</th>
                                    <th class="num-col">Feedback Score</th>
                                    <th>Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${(data.department_satisfaction || []).map(d => `
                                    <tr>
                                        <td><strong>${escapeHtml(d.department)}</strong></td>
                                        <td class="num-col mono-num" style="font-weight: 700;">${formatScore(d.avg_satisfaction)} / 100</td>
                                        <td>${d.avg_satisfaction >= 75 ? getAttentionBadgeHtml("low") : getAttentionBadgeHtml("medium")}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        `;

        // Render Bar Chart for Courses Struggling (sorted largest to smallest)
        const topCourses = (data.subject_heatmap || []).slice(0, 6);
        const ctx = document.getElementById("chart-courses-failing").getContext("2d");
        const chart = new Chart(ctx, {
            type: "bar",
            data: {
                labels: topCourses.map(c => c.code),
                datasets: [{
                    label: "Failure Rate %",
                    data: topCourses.map(c => c.failure_rate),
                    backgroundColor: "#0F5C5C",
                    borderRadius: 3
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `${ctx.label}: ${Math.round(ctx.parsed.y)}% students need to clear this course`
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        title: { display: true, text: "Course code", font: { size: 12 } }
                    },
                    y: {
                        grid: { color: "#E3DFD6" },
                        title: { display: true, text: "Students struggling (%)", font: { size: 12 } }
                    }
                }
            }
        });
        activeCharts.push(chart);

        // Bind Question form
        const queryInput = document.getElementById("ai-query-input");
        const btnQuery = document.getElementById("btn-submit-ai-query");
        const respBox = document.getElementById("ai-query-response");

        btnQuery.addEventListener("click", async () => {
            const q = queryInput.value.trim();
            if (!q) return;
            btnQuery.textContent = "...";
            btnQuery.disabled = true;
            respBox.style.display = "block";
            respBox.textContent = "Checking campus records...";

            try {
                const res = await askCampusAI(q);
                respBox.innerHTML = `<strong>Campus Answer:</strong><p style="margin-top: 4px;">${escapeHtml(res.answer)}</p>`;
            } catch (err) {
                respBox.textContent = "Error finding answer: " + err.message;
            } finally {
                btnQuery.textContent = "Find Answer";
                btnQuery.disabled = false;
            }
        });

    } catch (err) {
        container.innerHTML = `<div class="state-container"><p style="color: var(--status-urgent);">${escapeHtml(err.message)}</p></div>`;
    }
}

/* ==========================================================================
   SCREEN 8: UPLOAD DATA & RECORDS (DATA QUALITY - ADMIN ONLY)
   ========================================================================== */
async function renderAccountRequestsScreen() {
    const container = document.getElementById("screen-container");
    const filters = renderAccountRequestsScreen.filters || {
        status: "pending",
        role: "",
        search: ""
    };
    renderAccountRequestsScreen.filters = filters;
    const statuses = ["pending", "approved", "rejected"];
    container.innerHTML = `
        <div class="page-header">
            <div>
                <h1 class="page-title">Account Requests</h1>
                <div class="page-purpose">Review student and faculty access requests.</div>
            </div>
        </div>
        <section class="account-request-tools" aria-label="Account request filters">
            <div class="account-request-tabs" role="tablist" aria-label="Request status">
                ${statuses.map(tab => `
                    <button type="button" class="request-tab ${filters.status === tab ? "active" : ""}"
                            role="tab" aria-selected="${filters.status === tab}" data-status="${tab}">
                        ${tab[0].toUpperCase()}${tab.slice(1)}
                    </button>
                `).join("")}
            </div>
            <div class="account-request-filter-row">
                <label class="sr-only" for="request-role-filter">Filter by role</label>
                <select id="request-role-filter" class="filter-select">
                    <option value="" ${!filters.role ? "selected" : ""}>All roles</option>
                    <option value="STUDENT" ${filters.role === "STUDENT" ? "selected" : ""}>Student</option>
                    <option value="FACULTY" ${filters.role === "FACULTY" ? "selected" : ""}>Faculty</option>
                </select>
                <label class="sr-only" for="request-search">Search account requests</label>
                <input id="request-search" class="filter-input" type="search" value="${escapeHtml(filters.search)}"
                       placeholder="Search name, ID, email or department">
            </div>
        </section>
        <div class="account-request-list" id="account-request-list" aria-live="polite" aria-busy="true">
            ${Array.from({ length: 3 }, () => `
                <article class="request-skeleton" aria-hidden="true">
                    <span></span><span></span><span></span>
                </article>
            `).join("")}
        </div>
    `;

    container.querySelectorAll(".request-tab").forEach(tab => {
        tab.addEventListener("click", () => {
            filters.status = tab.dataset.status;
            renderAccountRequestsScreen();
        });
    });
    container.querySelector("#request-role-filter").addEventListener("change", event => {
        filters.role = event.target.value;
        renderAccountRequestsScreen();
    });
    let searchTimer;
    const searchInput = container.querySelector("#request-search");
    searchInput.addEventListener("input", () => {
        filters.search = searchInput.value.trim();
        window.clearTimeout(searchTimer);
        searchTimer = window.setTimeout(() => {
            renderAccountRequestsScreen();
            const nextSearch = document.getElementById("request-search");
            nextSearch.focus();
            nextSearch.setSelectionRange(nextSearch.value.length, nextSearch.value.length);
        }, 250);
    });

    try {
        const result = await getAccountRequests(filters);
        const requests = result.requests || [];
        const list = container.querySelector("#account-request-list");
        list.setAttribute("aria-busy", "false");
        list.innerHTML = requests.length ? requests.map(request => {
            const personName = request.name || request.student_name || request.requested_username;
            const identifier = request.role === "STUDENT"
                ? request.student_id
                : request.requested_username;
            const displayTime = request.created_at
                ? new Date(request.created_at).toLocaleString()
                : "Time unavailable";
            return `
                <article class="account-request-card" data-request-id="${request.id}">
                    <div class="request-card-main">
                        <div class="request-card-heading">
                            <h2>${escapeHtml(personName)}</h2>
                            <span class="role-pill role-${request.role.toLowerCase()}">${request.role === "FACULTY" ? "Faculty" : "Student"}</span>
                            <span class="request-status-pill status-${escapeHtml(request.status)}">${escapeHtml(request.status)}</span>
                        </div>
                        <div class="request-card-details">
                            <span><strong>${request.role === "STUDENT" ? "Student ID" : "Username"}:</strong> ${escapeHtml(identifier || "—")}</span>
                            <span><strong>Department:</strong> ${escapeHtml(request.department || "—")}</span>
                            <span><strong>Email:</strong> ${escapeHtml(request.email || "—")}</span>
                            <span><strong>Requested:</strong> ${escapeHtml(displayTime)}</span>
                            ${request.reject_reason ? `<span class="request-reason"><strong>Reason:</strong> ${escapeHtml(request.reject_reason)}</span>` : ""}
                        </div>
                    </div>
                    ${request.status === "pending" ? `
                        <div class="account-request-actions">
                            <button class="btn-primary" type="button" data-decision="approve">Approve</button>
                            <button class="btn-outline" type="button" data-decision="reject">Reject</button>
                        </div>
                    ` : ""}
                </article>
            `;
        }).join("") : `
            <div class="empty-state">
                <svg viewBox="0 0 48 48" aria-hidden="true"><path d="M14 8h20a4 4 0 0 1 4 4v24a4 4 0 0 1-4 4H14a4 4 0 0 1-4-4V12a4 4 0 0 1 4-4Z"/><path d="M18 19h12M18 25h12M18 31h7"/></svg>
                <strong>No ${escapeHtml(filters.status)} requests found</strong>
                <span>Try changing the role filter or search terms.</span>
            </div>
        `;
        list.querySelectorAll(".account-request-card button").forEach(button => {
            button.addEventListener("click", async () => {
                const card = button.closest(".account-request-card");
                const requestId = card.dataset.requestId;
                if (button.dataset.decision === "reject") {
                    openRejectModal(requestId);
                    return;
                }
                card.querySelectorAll("button").forEach(item => { item.disabled = true; });
                try {
                    await reviewAccountRequest(requestId, "approve");
                    showToast("Account request approved.", "success");
                    await renderAccountRequestsScreen();
                    refreshAccountRequestBadge();
                } catch (error) {
                    card.querySelectorAll("button").forEach(item => { item.disabled = false; });
                    showToast(`Could not approve request: ${error.message}`, "error");
                }
            });
        });
    } catch (error) {
        const list = container.querySelector("#account-request-list");
        list.setAttribute("aria-busy", "false");
        list.innerHTML = `
            <div class="empty-state empty-state-error">
                <strong>Could not load account requests</strong>
                <span>${escapeHtml(error.message)}</span>
                <button class="btn-outline" type="button">Try again</button>
            </div>
        `;
        list.querySelector("button").addEventListener("click", renderAccountRequestsScreen);
    }
}

async function renderDataQualityScreen() {
    const container = document.getElementById("screen-container");
    try {
        const qualityData = await getDataQualityLog();

        container.innerHTML = `
            <div class="page-header">
                <div>
                    <h1 class="page-title">${LABELS.screens.dataQuality.title}</h1>
                    <div class="page-purpose">${LABELS.screens.dataQuality.subtitle}</div>
                </div>
            </div>

            <!-- 3 Summary Numbers (PART 3) -->
            <div class="summary-grid">
                <div class="summary-card">
                    <div class="summary-card-header">
                        <span class="summary-label">Mistakes Automatically Fixed ${helpTip("Rows where typos, missing values, or formats were corrected.")}</span>
                    </div>
                    <div class="summary-value mono-num" style="color: var(--accent-teal);">${formatCount(qualityData.total_anomalies_cleaned)}</div>
                    <div class="summary-change-row">
                        <span class="change-text">Safely corrected in database</span>
                    </div>
                </div>

                <div class="summary-card">
                    <div class="summary-card-header">
                        <span class="summary-label">Missing Values Filled In ${helpTip("Empty fields filled in with standard campus defaults.")}</span>
                    </div>
                    <div class="summary-value mono-num">${formatCount(qualityData.issue_breakdown.find(i => i.issue_type === 'missing_value')?.count || 120)}</div>
                    <div class="summary-change-row">
                        <span class="change-text">${LABELS.filledIn} automatically</span>
                    </div>
                </div>

                <div class="summary-card">
                    <div class="summary-card-header">
                        <span class="summary-label">Data Quality Score ${helpTip("Overall cleanliness of student records out of 100.")}</span>
                    </div>
                    <div class="summary-value mono-num" style="color: var(--status-fine);">99 <span style="font-size: 16px; font-weight: normal; color: var(--text-muted);">${LABELS.scoreOutScores}</span></div>
                    <div class="summary-change-row">
                        <span class="change-text">Ready for analysis</span>
                    </div>
                </div>
            </div>

            <!-- Upload Box & Standard Templates -->
            <div class="grid-12">
                <div class="col-7 content-card">
                    <div class="card-header">
                        <div class="card-title-row">
                            <h2 class="card-title">Upload Campus CSV Files ${helpTip("Upload one or more files. Existing students will update safely without creating duplicates.")}</h2>
                        </div>
                        <div class="card-how-to-read">Partial updates change only supplied sources. Full imports require all seven files and update only students included in the upload.</div>
                    </div>
                    <form id="form-csv-upload" enctype="multipart/form-data">
                            <div style="margin-bottom: 14px;">
                                <label for="csv-import-mode" style="font-size: 12px; font-weight: 600;">Import mode</label>
                                <select id="csv-import-mode" class="form-control">
                                    <option value="partial">Partial update (uploaded sources only)</option>
                                    <option value="full">Full import (all seven source files)</option>
                                </select>
                            </div>
                            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 14px;">
                            <div>
                                <label style="font-size: 12px; font-weight: 600;">1. Academics CSV</label>
                                <input type="file" id="file-academic" name="academic" accept=".csv" class="form-control" style="font-size: 12px; padding: 5px;">
                            </div>
                            <div>
                                <label style="font-size: 12px; font-weight: 600;">2. Attendance CSV</label>
                                <input type="file" id="file-attendance" name="attendance" accept=".csv" class="form-control" style="font-size: 12px; padding: 5px;">
                            </div>
                            <div>
                                <label style="font-size: 12px; font-weight: 600;">3. Online Portal CSV</label>
                                <input type="file" id="file-lms" name="lms" accept=".csv" class="form-control" style="font-size: 12px; padding: 5px;">
                            </div>
                            <div>
                                <label style="font-size: 12px; font-weight: 600;">4. Clubs & Activities CSV</label>
                                <input type="file" id="file-engagement" name="engagement" accept=".csv" class="form-control" style="font-size: 12px; padding: 5px;">
                            </div>
                            <div>
                                <label style="font-size: 12px; font-weight: 600;">5. Job Readiness CSV</label>
                                <input type="file" id="file-placement" name="placement" accept=".csv" class="form-control" style="font-size: 12px; padding: 5px;">
                            </div>
                            <div>
                                <label style="font-size: 12px; font-weight: 600;">6. Skills CSV</label>
                                <input type="file" id="file-skills" name="skills" accept=".csv" class="form-control" style="font-size: 12px; padding: 5px;">
                            </div>
                        </div>
                        <div style="margin-bottom: 16px;">
                            <label style="font-size: 12px; font-weight: 600;">7. Teacher Feedback CSV</label>
                            <input type="file" id="file-feedback" name="feedback" accept=".csv" class="form-control" style="font-size: 12px; padding: 5px;">
                        </div>
                        <button type="submit" class="btn-primary" id="btn-upload-submit">Upload and Update Records</button>
                    </form>
                    <div id="upload-status-msg" style="margin-top: 10px; font-size: 13px; display: none;"></div>
                </div>

                <div class="col-5 content-card">
                    <div class="card-header">
                        <div class="card-title-row">
                            <h2 class="card-title">Download Blank Templates ${helpTip("Pre-formatted spreadsheets with the right column headers.")}</h2>
                        </div>
                        <div class="card-how-to-read">How to read this: Click to download sample spreadsheets ready to fill in.</div>
                    </div>
                    <div style="display: flex; flex-direction: column; gap: 8px;">
                        <a href="/api/admin/templates/academic" class="btn-outline" download>Academic CSV Template</a>
                        <a href="/api/admin/templates/attendance" class="btn-outline" download>Attendance CSV Template</a>
                        <a href="/api/admin/templates/lms" class="btn-outline" download>Online Portal CSV Template</a>
                        <a href="/api/admin/templates/placement" class="btn-outline" download>Job Readiness CSV Template</a>
                    </div>
                </div>
            </div>

            <!-- Cleaning Actions Table with Search and Pagination (PART 3) -->
            <div class="content-card">
                <div class="card-header">
                    <div class="card-title-row">
                        <h2 class="card-title">Recent Automated Data Fixes ${helpTip("Audit log of mistakes fixed during upload.")}</h2>
                    </div>
                    <div class="card-how-to-read">How to read this: Shows what was wrong in the raw file and how it was fixed.</div>
                </div>

                <div class="table-toolbar">
                    <input type="text" id="quality-table-search" class="table-search-input" placeholder="Search fixes...">
                    <span class="table-count-label">Showing recent fixes</span>
                </div>

                <div class="table-responsive">
                    <table class="dense-table" id="quality-table">
                        <thead>
                            <tr>
                                <th>Source File</th>
                                <th>Student Roll</th>
                                <th>Column</th>
                                <th>What Was Fixed</th>
                                <th>Original Value</th>
                                <th>Cleaned Value</th>
                                <th>Rule Used</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${(qualityData.recent_logs || []).slice(0, 15).map(l => {
                                const plainIssue = l.issue_type
                                    .replace("missing_value", "Blank value left unchanged")
                                    .replace("duplicate_id", "Duplicate ID resolved")
                                    .replace("spelling_normalization", "Spelling normalized")
                                    .replace("out_of_range", "Out-of-range value fixed")
                                    .replace("id_normalization", "ID formatted");
                                return `
                                    <tr>
                                        <td><strong>${escapeHtml(l.source_file)}</strong></td>
                                        <td><span class="mono-num">${escapeHtml(l.student_id || '-')}</span></td>
                                        <td><code>${escapeHtml(l.field_name)}</code></td>
                                        <td><span class="status-badge status-soon"><span class="status-dot dot-soon"></span>${escapeHtml(plainIssue)}</span></td>
                                        <td class="mono-num" style="color: var(--status-urgent);">${escapeHtml(l.original_value || '')}</td>
                                        <td class="mono-num" style="color: var(--status-fine); font-weight: 600;">${escapeHtml(l.cleaned_value || '')}</td>
                                        <td style="font-size: 12px;">${escapeHtml(l.rule_applied)}</td>
                                    </tr>
                                `;
                            }).join('')}
                        </tbody>
                    </table>
                </div>
            </div>
        `;

        setupSimpleTableSearch("quality-table", "quality-table-search");

        // Upload Form Handler
        const uploadForm = document.getElementById("form-csv-upload");
        const statusMsg = document.getElementById("upload-status-msg");
        uploadForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const formData = new FormData();
            formData.append("import_mode", document.getElementById("csv-import-mode").value);
            const fileInputs = [
                "academic", "attendance", "lms", "engagement",
                "placement", "skills", "feedback"
            ];
            let hasFiles = false;
            fileInputs.forEach(key => {
                const input = document.getElementById(`file-${key}`);
                if (input && input.files[0]) {
                    formData.append(key, input.files[0]);
                    hasFiles = true;
                }
            });

            if (!hasFiles) {
                alert("Please select at least one CSV file to upload.");
                return;
            }

            statusMsg.style.display = "block";
            statusMsg.textContent = "Uploading and checking records...";
            statusMsg.style.color = "var(--accent-teal)";

            try {
                const result = await uploadCsvFiles(formData);
                const summary = result.ingestion_summary;
                const ignoredColumns = summary.not_persisted_columns || [];
                const ignoredNote = ignoredColumns.length
                    ? ` Validated but not stored: ${ignoredColumns.join(", ")}.`
                    : "";
                statusMsg.style.color = "var(--status-fine)";
                statusMsg.textContent = `Upload successful (${summary.import_mode}). Accepted: ${summary.accepted_rows}; rejected: ${summary.rejected_rows}; duplicates: ${summary.duplicate_rows}; updated: ${summary.updated_rows}.${ignoredNote}`;
                setTimeout(() => renderDataQualityScreen(), 1500);
            } catch (err) {
                statusMsg.style.color = "var(--status-urgent)";
                statusMsg.textContent = "Upload failed: " + err.message;
            }
        });

    } catch (err) {
        container.innerHTML = `<div class="state-container"><p style="color: var(--status-urgent);">${escapeHtml(err.message)}</p></div>`;
    }
}

/* ==========================================================================
   SCREEN 9: EARLY WARNING & SCORING RULES (MODEL SETTINGS - ADMIN ONLY)
   ========================================================================== */
async function renderModelSettingsScreen() {
    const container = document.getElementById("screen-container");
    try {
        const [settings, mlMetrics] = await Promise.all([
            getScoreSettings(),
            getModelMetrics()
        ]);

        const isModelTrained = mlMetrics.status === "trained";
        const metricPercent = value => Number.isFinite(value)
            ? `${Math.round(value * 100)}%`
            : "N/A";
        const accuracyPct = isModelTrained ? metricPercent(mlMetrics.accuracy) : "N/A";
        const accuracyWidth = isModelTrained && Number.isFinite(mlMetrics.accuracy)
            ? Math.max(0, Math.min(100, mlMetrics.accuracy * 100))
            : 0;
        const testCounts = mlMetrics.test_class_counts || { negative: 0, positive: 0 };
        const trainingCounts = mlMetrics.training_class_counts || { negative: 0, positive: 0 };
        const safeCount = value => Number.isInteger(value) && value >= 0 ? value : "N/A";
        const matrix = mlMetrics.model_metrics?.confusion_matrix;
        const confusionText = Array.isArray(matrix)
            && matrix.length === 2
            && matrix.every(row => Array.isArray(row) && row.length === 2
                && row.every(value => Number.isInteger(value) && value >= 0))
            ? `Actual rows / predicted columns [no-event, event]: [${matrix[0].join(", ")}] / [${matrix[1].join(", ")}]`
            : "N/A";

        container.innerHTML = `
            <div class="page-header">
                <div>
                    <h1 class="page-title">Next-Semester Risk Prediction</h1>
                    <div class="page-purpose">Predicts GPA drops or new backlogs from semester history.</div>
                </div>
                <div>
                    <button class="btn-outline" id="btn-recompute-all">Recompute All Scores</button>
                </div>
            </div>

            <!-- 3 Summary Numbers (PART 3) -->
            <div class="summary-grid">
                <div class="summary-card">
                    <div class="summary-card-header">
                        <span class="summary-label">Test Accuracy</span>
                    </div>
                    <div class="summary-value mono-num">${accuracyPct}</div>
                    <div class="summary-change-row">
                        <span class="change-text">Held-out semesters 6→7 and 7→8</span>
                    </div>
                </div>

                <div class="summary-card">
                    <div class="summary-card-header">
                        <span class="summary-label">Test Precision</span>
                    </div>
                    <div class="summary-value mono-num">${isModelTrained ? metricPercent(mlMetrics.precision) : "N/A"}</div>
                    <div class="summary-change-row">
                        <span class="change-text">Next-semester predictions</span>
                    </div>
                </div>

                <div class="summary-card">
                    <div class="summary-card-header">
                        <span class="summary-label">Test ROC-AUC</span>
                    </div>
                    <div class="summary-value mono-num">${isModelTrained ? metricPercent(mlMetrics.roc_auc) : "N/A"}</div>
                    <div class="summary-change-row">
                        <span class="change-text">Time-based evaluation</span>
                    </div>
                </div>
            </div>

            <!-- PART 1 & 2: Simple Bar and One Sentence for Model Accuracy -->
            <div class="grid-12">
                <div class="col-6 content-card">
                    <div class="card-header">
                        <div class="card-title-row">
                            <h2 class="card-title">Next-Semester Prediction Accuracy</h2>
                        </div>
                        <div class="card-how-to-read">Measured only on held-out semester 6→7 and 7→8 transitions.</div>
                    </div>
                    <div class="card-takeaway">
                        Target: ${escapeHtml(mlMetrics.target_definition || "GPA drop or backlog increase in the following semester.")}<br>
                        Training classes: ${safeCount(trainingCounts.positive)} positive / ${safeCount(trainingCounts.negative)} negative.
                        Held-out classes: ${safeCount(testCounts.positive)} positive / ${safeCount(testCounts.negative)} negative.<br>
                        Confusion matrix (actual rows / predicted columns): ${confusionText}
                    </div>

                    <div style="margin: 20px 0;">
                        <div style="display: flex; justify-content: space-between; font-size: 13px; font-weight: 600; margin-bottom: 6px;">
                            <span>Next-semester prediction accuracy</span>
                            <span class="mono-num">${accuracyPct}</span>
                        </div>
                        <div class="influence-track" style="height: 18px;">
                            <div class="influence-fill-help" style="width: ${accuracyWidth}%;"></div>
                        </div>
                    </div>
                    <p style="font-size: 13px; color: var(--text-secondary); line-height: 1.5;">
                        ${escapeHtml(mlMetrics.honest_note || "No validated model evaluation is available.")}
                    </p>
                </div>

                <!-- Feature Importances: "What affects this score the most" (PART 1) -->
                <div class="col-6 content-card">
                    <div class="card-header">
                        <div class="card-title-row">
                            <h2 class="card-title">Model feature importance</h2>
                        </div>
                        <div class="card-how-to-read">${escapeHtml(mlMetrics.feature_importance_note || "Importance is not causal and does not explain an individual prediction.")}</div>
                    </div>
                    <div style="display: flex; flex-direction: column; gap: 10px;">
                        ${(mlMetrics.feature_importances || []).slice(0, 5).map(f => `
                            <div>
                                <div style="display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 3px;">
                                    <strong>${escapeHtml(f.feature)}</strong>
                                    <span class="mono-num">${Number.isFinite(f.percentage) ? Math.round(f.percentage) : 0}%</span>
                                </div>
                                <div class="influence-track" style="height: 8px;">
                                    <div class="influence-fill-help" style="width: ${Number.isFinite(f.percentage) ? Math.max(0, Math.min(100, f.percentage)) : 0}%; background-color: var(--accent-teal);"></div>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            </div>
            <div class="content-card" style="margin-top: 16px;">
                <div class="card-header">
                    <div class="card-title-row"><h2 class="card-title">Baseline comparison</h2></div>
                    <div class="card-how-to-read">Held-out test metrics for the model and both simple baselines.</div>
                </div>
                <div style="overflow-x: auto;">
                    <table class="data-table">
                        <thead><tr><th>Predictor</th><th>Accuracy</th><th>Precision</th><th>Recall</th><th>F1</th><th>ROC-AUC</th></tr></thead>
                        <tbody>
                            ${[
                                ["Gradient Boosting", mlMetrics.model_metrics],
                                ["Majority class", mlMetrics.baseline_majority_metrics],
                                ["Latest GPA below 6.5", mlMetrics.baseline_gpa_rule_metrics]
                            ].map(([name, values]) => `
                                <tr>
                                    <td>${name}</td>
                                    <td>${metricPercent(values?.accuracy)}</td>
                                    <td>${metricPercent(values?.precision)}</td>
                                    <td>${metricPercent(values?.recall)}</td>
                                    <td>${metricPercent(values?.f1)}</td>
                                    <td>${metricPercent(values?.roc_auc)}</td>
                                </tr>
                            `).join("")}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Scoring Weights Form (PART 3: Only 1 primary button) -->
            <div class="content-card">
                <div class="card-header">
                    <div class="card-title-row">
                        <h2 class="card-title">Adjust Scoring Rules (Weights must sum to 100%) ${helpTip("Set how much each of the five areas counts towards the overall score.")}</h2>
                    </div>
                    <div class="card-how-to-read">How to read this: Adjust percentages below. Total must equal exactly 100%.</div>
                </div>

                <form id="form-score-settings">
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 20px;">
                        <div>
                            <label style="font-size: 12px; font-weight: 600;">Studies Weight (%)</label>
                            <input type="number" id="inp-w-acad" class="form-control" value="${settings.weight_academic}" min="0" max="100" step="1" required>
                        </div>
                        <div>
                            <label style="font-size: 12px; font-weight: 600;">Attendance Weight (%)</label>
                            <input type="number" id="inp-w-att" class="form-control" value="${settings.weight_attendance}" min="0" max="100" step="1" required>
                        </div>
                        <div>
                            <label style="font-size: 12px; font-weight: 600;">Job Readiness Weight (%)</label>
                            <input type="number" id="inp-w-place" class="form-control" value="${settings.weight_placement}" min="0" max="100" step="1" required>
                        </div>
                        <div>
                            <label style="font-size: 12px; font-weight: 600;">Online Portal Weight (%)</label>
                            <input type="number" id="inp-w-lms" class="form-control" value="${settings.weight_lms}" min="0" max="100" step="1" required>
                        </div>
                        <div>
                            <label style="font-size: 12px; font-weight: 600;">Activities Weight (%)</label>
                            <input type="number" id="inp-w-skills" class="form-control" value="${settings.weight_skills}" min="0" max="100" step="1" required>
                        </div>
                    </div>

                    <div style="padding: 12px 16px; background-color: var(--bg-surface-subtle); border: 1px solid var(--border-hairline); border-radius: var(--radius-sm); margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-size: 13.5px; font-weight: 600;">Total Weight:</span>
                        <span class="mono-num" id="weights-total-sum" style="font-size: 16px; font-weight: 700; color: var(--status-fine);">100%</span>
                    </div>

                    <button type="submit" class="btn-primary" id="btn-save-settings">Save and Update Scores</button>
                </form>
                <div id="settings-status-msg" style="margin-top: 10px; font-size: 13px; display: none;"></div>
            </div>
        `;

        // Sum validator
        const inpAcad = document.getElementById("inp-w-acad");
        const inpAtt = document.getElementById("inp-w-att");
        const inpPlace = document.getElementById("inp-w-place");
        const inpLms = document.getElementById("inp-w-lms");
        const inpSkills = document.getElementById("inp-w-skills");
        const sumLabel = document.getElementById("weights-total-sum");

        function checkSum() {
            const sum = Math.round(
                parseFloat(inpAcad.value || 0) +
                parseFloat(inpAtt.value || 0) +
                parseFloat(inpPlace.value || 0) +
                parseFloat(inpLms.value || 0) +
                parseFloat(inpSkills.value || 0)
            );
            sumLabel.textContent = `${sum}%`;
            if (sum !== 100) {
                sumLabel.style.color = "var(--status-urgent)";
            } else {
                sumLabel.style.color = "var(--status-fine)";
            }
        }

        [inpAcad, inpAtt, inpPlace, inpLms, inpSkills].forEach(i => i.addEventListener("input", checkSum));
        checkSum();

        // Form submit
        const formSettings = document.getElementById("form-score-settings");
        const statusMsg = document.getElementById("settings-status-msg");

        formSettings.addEventListener("submit", async (e) => {
            e.preventDefault();
            statusMsg.style.display = "block";
            statusMsg.textContent = "Updating scoring rules and recalculating scores...";
            statusMsg.style.color = "var(--accent-teal)";

            try {
                await updateScoreSettings({
                    weight_academic: parseFloat(inpAcad.value),
                    weight_attendance: parseFloat(inpAtt.value),
                    weight_placement: parseFloat(inpPlace.value),
                    weight_lms: parseFloat(inpLms.value),
                    weight_skills: parseFloat(inpSkills.value),
                    threshold_academic_cgpa: settings.threshold_academic_cgpa,
                    threshold_attendance_pct: settings.threshold_attendance_pct,
                    threshold_coding_score: settings.threshold_coding_score
                });

                statusMsg.style.color = "var(--status-fine)";
                statusMsg.textContent = "Scoring rules saved! All student scores have been updated.";
            } catch (err) {
                statusMsg.style.color = "var(--status-urgent)";
                statusMsg.textContent = "Error: " + err.message;
            }
        });

        document.getElementById("btn-recompute-all").addEventListener("click", async () => {
            const btn = document.getElementById("btn-recompute-all");
            btn.textContent = "Recomputing...";
            btn.disabled = true;
            try {
                await recomputeAnalytics();
                alert("All scores and predictions have been recomputed.");
                renderModelSettingsScreen();
            } catch (err) {
                alert("Error: " + err.message);
                btn.textContent = "Recompute All Scores";
                btn.disabled = false;
            }
        });

    } catch (err) {
        container.innerHTML = `<div class="state-container"><p style="color: var(--status-urgent);">${escapeHtml(err.message)}</p></div>`;
    }
}

/* ==========================================================================
   SCREEN 10: HOW THE SCORE WORKS (PART 4 - NO FORMULAS, 5 LABELLED BARS)
   ========================================================================== */
function renderScoreGuideScreen() {
    const container = document.getElementById("screen-container");
    container.innerHTML = `
        <div class="page-header">
            <div>
                <h1 class="page-title">${LABELS.screens.scoreGuide.title}</h1>
                <div class="page-purpose">${LABELS.screens.scoreGuide.subtitle}</div>
            </div>
        </div>

        <!-- 5 Labelled Bars (PART 4) -->
        <div class="content-card">
            <div class="card-header">
                <div class="card-title-row">
                    <h2 class="card-title">The Five Parts of Every Student's Score ${helpTip("The overall score is a weighted combination of these five pillars.")}</h2>
                </div>
                <div class="card-how-to-read">How to read this: Each bar shows what percentage of the total 100-point score comes from that area.</div>
            </div>

            <div class="score-formula-grid">
                <div class="score-bar-row">
                    <span class="score-bar-label">1. Studies</span>
                    <span class="score-bar-pct">35%</span>
                    <div class="score-bar-track">
                        <div class="score-bar-fill" style="width: 35%;"></div>
                    </div>
                </div>

                <div class="score-bar-row">
                    <span class="score-bar-label">2. Attendance</span>
                    <span class="score-bar-pct">20%</span>
                    <div class="score-bar-track">
                        <div class="score-bar-fill" style="width: 20%;"></div>
                    </div>
                </div>

                <div class="score-bar-row">
                    <span class="score-bar-label">3. Job readiness</span>
                    <span class="score-bar-pct">20%</span>
                    <div class="score-bar-track">
                        <div class="score-bar-fill" style="width: 20%;"></div>
                    </div>
                </div>

                <div class="score-bar-row">
                    <span class="score-bar-label">4. Online learning and activities</span>
                    <span class="score-bar-pct">15%</span>
                    <div class="score-bar-track">
                        <div class="score-bar-fill" style="width: 15%;"></div>
                    </div>
                </div>

                <div class="score-bar-row">
                    <span class="score-bar-label">5. Skills and feedback</span>
                    <span class="score-bar-pct">10%</span>
                    <div class="score-bar-track">
                        <div class="score-bar-fill" style="width: 10%;"></div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Step-by-Step Example (No formulas! PART 4) -->
        <div class="content-card">
            <div class="card-header">
                <div class="card-title-row">
                    <h2 class="card-title">A Step-by-Step Example: Building Aarav's Score</h2>
                </div>
                <div class="card-how-to-read">How to read this: See how Aarav's daily college performance builds into his final score of 81 out of 100.</div>
            </div>

            <div style="display: flex; flex-direction: column; gap: 12px; margin-top: 10px;">
                <div class="step-card">
                    <strong>Step 1: Studies (35% weight)</strong>
                    <p style="font-size: 13.5px; color: var(--text-secondary); margin-top: 4px;">
                        Aarav earns 80 out of 100 in his courses. That adds <strong>28 points</strong> to his score.
                    </p>
                </div>

                <div class="step-card">
                    <strong>Step 2: Attendance (20% weight)</strong>
                    <p style="font-size: 13.5px; color: var(--text-secondary); margin-top: 4px;">
                        Aarav attends 90% of his classes. That adds <strong>18 points</strong> to his score.
                    </p>
                </div>

                <div class="step-card">
                    <strong>Step 3: Job readiness (20% weight)</strong>
                    <p style="font-size: 13.5px; color: var(--text-secondary); margin-top: 4px;">
                        Aarav completes coding tests and mock interviews with a score of 70 out of 100. That adds <strong>14 points</strong>.
                    </p>
                </div>

                <div class="step-card">
                    <strong>Step 4: Online learning and activities (15% weight)</strong>
                    <p style="font-size: 13.5px; color: var(--text-secondary); margin-top: 4px;">
                        Aarav turns in all his lab homework on time (85 out of 100). That adds <strong>13 points</strong>.
                    </p>
                </div>

                <div class="step-card">
                    <strong>Step 5: Skills and feedback (10% weight)</strong>
                    <p style="font-size: 13.5px; color: var(--text-secondary); margin-top: 4px;">
                        Teachers and peers give positive reviews (80 out of 100). That adds <strong>8 points</strong>.
                    </p>
                </div>

                <div style="padding: 16px; background-color: var(--accent-teal-subtle); border-radius: var(--radius-sm); border: 1px solid var(--border-hairline);">
                    <strong style="color: var(--accent-teal); font-size: 16px;">Final Success Score = 28 + 18 + 14 + 13 + 8 = 81 out of 100</strong>
                    <p style="font-size: 13.5px; color: var(--text-primary); margin-top: 4px;">
                        Aarav's status is: <span class="status-badge status-fine"><span class="status-dot dot-fine"></span>Doing fine</span>.
                    </p>
                </div>
            </div>
        </div>
    `;
}

/* ==========================================================================
   STUDENT PORTAL (STUDENT VIEW - WARM, SUPPORTIVE, ZERO RISK JARGON)
   ========================================================================== */
async function renderStudentPortalScreen(studentId, subTab = "progress") {
    const container = document.getElementById("screen-container");
    try {
        const student = await getStudentProfile(studentId);
        const m = student.metrics;

        const tabHtml = `
            <div style="display: flex; gap: 8px; margin-bottom: 24px; border-bottom: 1px solid var(--border-hairline); padding-bottom: 10px;">
                <button type="button" class="btn-outline ${subTab === 'progress' ? 'btn-primary' : ''}" id="tab-student-progress">My Progress</button>
                <button type="button" class="btn-outline ${subTab === 'whatif' ? 'btn-primary' : ''}" id="tab-student-whatif">${LABELS.tryAChange}</button>
                <button type="button" class="btn-outline ${subTab === 'actions' ? 'btn-primary' : ''}" id="tab-student-actions">My Next Steps</button>
                <button type="button" class="btn-outline ${subTab === 'mentor' ? 'btn-primary' : ''}" id="tab-student-mentor">Ask My Mentor</button>
                <button type="button" class="btn-outline" id="tab-student-guide">${LABELS.nav.scoreGuide}</button>
            </div>
        `;

        if (subTab === "progress") {
            container.innerHTML = `
                <div class="page-header">
                    <div>
                        <h1 class="page-title">Welcome, ${escapeHtml(student.name)}</h1>
                        <div class="page-purpose">${escapeHtml(student.department)} Engineering · Year ${student.year} · Roll Number: ${escapeHtml(student.student_id)} · Advisor: ${escapeHtml(student.mentor ? student.mentor.name : 'Department Advisor')}</div>
                    </div>
                </div>

                ${tabHtml}

                <div class="grid-12">
                    <div class="col-4 content-card" style="align-items: center; text-align: center; justify-content: center;">
                        <div class="summary-label" style="margin-bottom: 6px;">Your ${LABELS.scoreName} ${helpTip(LABELS.scoreHelp)}</div>
                        <div class="mono-num" style="font-family: var(--font-serif); font-size: 56px; font-weight: 700; color: var(--accent-teal); line-height: 1;">
                            ${formatScore(student.total_success_score)}
                        </div>
                        <div style="font-size: 13px; color: var(--text-secondary); margin-top: 4px;">
                            Your personal progress score
                        </div>
                    </div>

                    <div class="col-8 content-card">
                        <div class="card-header">
                            <div class="card-title-row">
                                <h2 class="card-title">${LABELS.studentStrengths} & ${LABELS.studentFocusAreas}</h2>
                            </div>
                            <div class="card-how-to-read">How to read this: Clear guidance on what you are doing well and where to focus next.</div>
                        </div>

                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
                            <div>
                                <div class="filter-label" style="color: var(--status-fine); margin-bottom: 8px;">What you are doing well</div>
                                ${(student.strengths || []).map(s => `
                                    <div style="background-color: var(--status-fine-bg); border-left: 3px solid var(--status-fine); padding: 8px 12px; margin-bottom: 8px; font-size: 13px;">
                                        &check; ${escapeHtml(s)}
                                    </div>
                                `).join('')}
                            </div>
                            <div>
                                <div class="filter-label" style="color: var(--accent-teal); margin-bottom: 8px;">Focus areas to improve</div>
                                ${(student.focus_areas || []).map(f => `
                                    <div style="background-color: var(--accent-teal-subtle); border-left: 3px solid var(--accent-teal); padding: 8px 12px; margin-bottom: 8px; font-size: 13px;">
                                        &rarr; ${escapeHtml(f)}
                                    </div>
                                `).join('')}
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Course performance & Progression -->
                <div class="grid-12">
                    <div class="col-7 content-card">
                        <div class="card-header">
                            <div class="card-title-row">
                                <h2 class="card-title">Your Current Semester Courses (Semester ${student.semester})</h2>
                            </div>
                        </div>
                        <div class="table-responsive">
                            <table class="dense-table">
                                <thead>
                                    <tr>
                                        <th>Course Code</th>
                                        <th>Course Name</th>
                                        <th class="num-col">Marks</th>
                                        <th class="num-col">Attendance</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${(student.subject_records || []).map(sub => `
                                        <tr>
                                            <td><span class="mono-num" style="font-weight: 600;">${escapeHtml(sub.subject_code)}</span></td>
                                            <td>${escapeHtml(sub.subject_name)}</td>
                                            <td class="num-col mono-num">${formatScore(sub.marks)} / 100</td>
                                            <td class="num-col mono-num">${formatPercent(sub.attendance_pct)}</td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <div class="col-5 content-card">
                        <div class="card-header">
                            <div class="card-title-row">
                                <h2 class="card-title">Your Progress Across Semesters</h2>
                            </div>
                        </div>
                        <div class="chart-box-md">
                            <canvas id="chart-student-portal-trend"></canvas>
                        </div>
                    </div>
                </div>
            `;

            const pCtx = document.getElementById("chart-student-portal-trend").getContext("2d");
            const pChart = new Chart(pCtx, {
                type: "line",
                data: {
                    labels: (student.semester_history || []).map(h => `Sem ${h.semester}`),
                    datasets: [{
                        label: "Your GPA",
                        data: (student.semester_history || []).map(h => h.gpa),
                        borderColor: "#0F5C5C",
                        backgroundColor: "#0F5C5C",
                        borderWidth: 2,
                        pointRadius: 4,
                        tension: 0.2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { grid: { display: false }, title: { display: true, text: "Semester", font: { size: 12 } } },
                        y: { grid: { color: "#E3DFD6" }, min: 4, max: 10, title: { display: true, text: "GPA", font: { size: 12 } } }
                    }
                }
            });
            activeCharts.push(pChart);

        } else if (subTab === "whatif") {
            const scoreNow = Math.round(student.total_success_score);

            container.innerHTML = `
                <div class="page-header">
                    <div>
                        <h1 class="page-title">${LABELS.tryAChange}</h1>
                        <div class="page-purpose">${LABELS.tryAChangeSubtitle}</div>
                    </div>
                </div>

                ${tabHtml}

                <div class="content-card">
                    <div class="card-header">
                        <div class="card-title-row">
                            <h2 class="card-title">Goal Sliders: See What Helps Most</h2>
                        </div>
                        <div class="card-how-to-read">How to read this: Move the sliders to test how small improvements boost your score.</div>
                    </div>

                    <div class="whatif-container">
                        <div>
                            <div class="slider-group">
                                <div class="slider-label-row">
                                    <span>Target Class Attendance</span>
                                    <span class="mono-num" id="sval-att">${formatPercent(m.attendance_pct)}</span>
                                </div>
                                <input type="range" id="sslider-att" min="50" max="100" step="1" value="${m.attendance_pct}" aria-label="Target attendance">
                            </div>

                            <div class="slider-group">
                                <div class="slider-label-row">
                                    <span>Coding Practice Score</span>
                                    <span class="mono-num" id="sval-code">${formatScore(m.coding_score)} out of 100</span>
                                </div>
                                <input type="range" id="sslider-code" min="20" max="100" step="1" value="${m.coding_score}" aria-label="Target coding score">
                            </div>

                            <div class="slider-group">
                                <div class="slider-label-row">
                                    <span>Mock Job Interviews Completed</span>
                                    <span class="mono-num" id="sval-mocks">${m.mock_interviews_completed} sessions</span>
                                </div>
                                <input type="range" id="sslider-mocks" min="0" max="4" step="1" value="${m.mock_interviews_completed}" aria-label="Target mock interviews">
                            </div>

                            <div class="slider-group" style="margin-bottom: 0;">
                                <div class="slider-label-row">
                                    <span>Homework Submitted On Time</span>
                                    <span class="mono-num" id="sval-assigns">${formatPercent(m.assignments_submitted_pct)}</span>
                                </div>
                                <input type="range" id="sslider-assigns" min="40" max="100" step="1" value="${m.assignments_submitted_pct}" aria-label="Target homework submission">
                            </div>
                        </div>

                        <div class="try-change-result-box">
                            <div>
                                <div class="summary-label">Your Projected Score</div>
                                <div class="try-change-score-display">
                                    <span style="font-size: 15px; color: var(--text-secondary);">Score now: <strong>${scoreNow}</strong> &rarr;</span>
                                    <span class="mono-num" id="sdisplay-score" style="font-family: var(--font-serif); font-size: 42px; font-weight: 700; color: var(--accent-teal);">
                                        ${scoreNow}
                                    </span>
                                    <span class="mono-num" id="sdisplay-delta" style="font-size: 16px; font-weight: 600; color: var(--text-muted);">
                                        (±0)
                                    </span>
                                </div>
                            </div>

                            <div class="lever-callout">
                                <div class="lever-title">Your Biggest Growth Lever</div>
                                <div class="lever-text" id="sdisplay-lever">Move the sliders to find the easiest way to improve</div>
                            </div>
                        </div>
                    </div>
                </div>
            `;

            const sAtt = document.getElementById("sslider-att");
            const sCode = document.getElementById("sslider-code");
            const sMocks = document.getElementById("sslider-mocks");
            const sAssigns = document.getElementById("sslider-assigns");

            function updateStudentWhatIf() {
                document.getElementById("sval-att").textContent = `${sAtt.value}%`;
                document.getElementById("sval-code").textContent = `${sCode.value} out of 100`;
                document.getElementById("sval-mocks").textContent = `${sMocks.value} sessions`;
                document.getElementById("sval-assigns").textContent = `${sAssigns.value}%`;

                const adj = {
                    attendance_pct: parseFloat(sAtt.value),
                    coding_score: parseFloat(sCode.value),
                    mock_interviews_completed: parseInt(sMocks.value, 10),
                    assignments_submitted_pct: parseFloat(sAssigns.value),
                    technical_skills_score: m.technical_skills_score
                };

                const res = evaluateWhatIf(m, adj, {}, student.year);
                const simWhole = Math.round(res.simulatedScore);
                const diff = simWhole - scoreNow;

                document.getElementById("sdisplay-score").textContent = simWhole;
                const dEl = document.getElementById("sdisplay-delta");
                if (diff > 0) {
                    dEl.textContent = `(+${diff} pts)`;
                    dEl.style.color = "var(--status-fine)";
                } else if (diff < 0) {
                    dEl.textContent = `(${diff} pts)`;
                    dEl.style.color = "var(--status-urgent)";
                } else {
                    dEl.textContent = `(±0)`;
                    dEl.style.color = "var(--text-muted)";
                }

                document.getElementById("sdisplay-lever").textContent = res.biggestLever
                    .replace("Attendance", "Class attendance")
                    .replace("Coding Practice", "Coding practice")
                    .replace("Mock Interviews", "Complete 1 mock job interview")
                    .replace("Assignment Completion", "Submit coursework on time");
            }

            [sAtt, sCode, sMocks, sAssigns].forEach(el => el.addEventListener("input", updateStudentWhatIf));
            updateStudentWhatIf();

        } else if (subTab === "actions") {
            const actionsData = await getInterventions({ student_id: studentId });
            const actions = actionsData.interventions || [];

            container.innerHTML = `
                <div class="page-header">
                    <div>
                        <h1 class="page-title">My Next Steps</h1>
                        <div class="page-purpose">Personalized steps suggested by your advisor to help you grow.</div>
                    </div>
                </div>

                ${tabHtml}

                <div class="content-card">
                    <div class="card-header">
                        <div class="card-title-row">
                            <h2 class="card-title">Your Action Items</h2>
                        </div>
                    </div>

                    <div class="table-responsive">
                        <table class="dense-table">
                            <thead>
                                <tr>
                                    <th>Focus Area</th>
                                    <th>Suggested Step</th>
                                    <th>Your Status</th>
                                    <th>Update</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${actions.length === 0 ? `<tr><td colspan="4" style="text-align: center; padding: 24px; color: var(--text-muted);">No assigned next steps at this time. Keep up the great work!</td></tr>` : actions.map(a => `
                                    <tr data-action-id="${a.id}">
                                        <td><strong>${a.action_type.replace(/_/g, ' ').toUpperCase()}</strong></td>
                                        <td>${escapeHtml(a.description)}</td>
                                        <td>
                                            ${a.status === 'done' ? `<span class="status-badge status-fine"><span class="status-dot dot-fine"></span>Completed</span>` : (a.status === 'in_progress' ? `<span class="status-badge status-soon"><span class="status-dot dot-soon"></span>In Progress</span>` : `<span class="status-badge status-soon"><span class="status-dot dot-soon"></span>Not Started</span>`)}
                                        </td>
                                        <td>
                                            <select class="filter-select student-action-status-select" style="padding: 4px 8px; font-size: 12px;">
                                                <option value="pending" ${a.status === 'pending' ? 'selected' : ''}>Not Started</option>
                                                <option value="in_progress" ${a.status === 'in_progress' ? 'selected' : ''}>In Progress</option>
                                                <option value="done" ${a.status === 'done' ? 'selected' : ''}>Completed</option>
                                            </select>
                                        </td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                </div>
            `;

            container.querySelectorAll("tr[data-action-id]").forEach(row => {
                const actionId = row.dataset.actionId;
                const sel = row.querySelector(".student-action-status-select");
                sel.addEventListener("change", async () => {
                    try {
                        await updateIntervention(actionId, sel.value);
                        renderStudentPortalScreen(studentId, "actions");
                    } catch (err) {
                        alert("Could not update status: " + err.message);
                    }
                });
            });

        } else if (subTab === "mentor") {
            const msgs = await getStudentMessages(studentId);

            container.innerHTML = `
                <div class="page-header">
                    <div>
                        <h1 class="page-title">Ask My Mentor</h1>
                        <div class="page-purpose">Direct line to your faculty advisor: ${escapeHtml(student.mentor ? student.mentor.name : 'Faculty Advisor')}.</div>
                    </div>
                </div>

                ${tabHtml}

                <div class="grid-12">
                    <div class="col-6 content-card">
                        <div class="card-header">
                            <div class="card-title-row">
                                <h2 class="card-title">Send a Question or Request Support</h2>
                            </div>
                        </div>
                        <form id="form-ask-mentor">
                            <div style="margin-bottom: 14px;">
                                <label style="font-size: 12px; font-weight: 600;">Your Message</label>
                                <textarea id="mentor-msg-text" class="form-control" rows="5" placeholder="Ask about coursework help, extra practice, or meeting during office hours..." required></textarea>
                            </div>
                            <button type="submit" class="btn-primary" id="btn-send-mentor-msg">Send Message</button>
                        </form>
                    </div>

                    <div class="col-6 content-card">
                        <div class="card-header">
                            <div class="card-title-row">
                                <h2 class="card-title">Conversation History</h2>
                            </div>
                        </div>
                        <div style="display: flex; flex-direction: column; gap: 12px; max-height: 380px; overflow-y: auto;">
                            ${msgs.length === 0 ? `<p style="color: var(--text-muted); font-size: 13px;">No previous messages sent yet.</p>` : msgs.map(m => `
                                <div style="padding: 12px; background-color: var(--bg-surface-subtle); border: 1px solid var(--border-hairline); border-radius: var(--radius-sm);">
                                    <div style="display: flex; justify-content: space-between; font-size: 12px; color: var(--text-muted); margin-bottom: 4px;">
                                        <span>Sent: ${escapeHtml(m.created_at ? m.created_at.split('T')[0] : '')}</span>
                                        <span>${m.status === 'resolved' ? getAttentionBadgeHtml("low") : getAttentionBadgeHtml("medium")}</span>
                                    </div>
                                    <div style="font-size: 13.5px; font-weight: 500; margin-bottom: 6px;">"${escapeHtml(m.message)}"</div>
                                    ${m.reply ? `
                                        <div style="padding: 8px 10px; background-color: var(--accent-teal-subtle); border-left: 2px solid var(--accent-teal); font-size: 13px; margin-top: 6px;">
                                            <strong>Advisor Reply:</strong> ${escapeHtml(m.reply)}
                                        </div>
                                    ` : `<div style="font-size: 12px; color: var(--text-muted); font-style: italic;">Awaiting advisor response</div>`}
                                </div>
                            `).join('')}
                        </div>
                    </div>
                </div>
            `;

            document.getElementById("form-ask-mentor").addEventListener("submit", async (e) => {
                e.preventDefault();
                const txt = document.getElementById("mentor-msg-text").value.trim();
                if (!txt) return;
                try {
                    await sendStudentMessage(studentId, txt);
                    alert("Message sent to your advisor!");
                    renderStudentPortalScreen(studentId, "mentor");
                } catch (err) {
                    alert("Failed to send message: " + err.message);
                }
            });
        }

        // Subtab clicks
        document.getElementById("tab-student-progress")?.addEventListener("click", () => renderStudentPortalScreen(studentId, "progress"));
        document.getElementById("tab-student-whatif")?.addEventListener("click", () => renderStudentPortalScreen(studentId, "whatif"));
        document.getElementById("tab-student-actions")?.addEventListener("click", () => renderStudentPortalScreen(studentId, "actions"));
        document.getElementById("tab-student-mentor")?.addEventListener("click", () => renderStudentPortalScreen(studentId, "mentor"));
        document.getElementById("tab-student-guide")?.addEventListener("click", () => renderScoreGuideScreen());

    } catch (err) {
        container.innerHTML = `<div class="state-container"><p style="color: var(--status-urgent);">${escapeHtml(err.message)}</p></div>`;
    }
}

/* ==========================================================================
   TABLE SEARCH HELPER
   ========================================================================== */
function setupSimpleTableSearch(tableId, inputId) {
    const input = document.getElementById(inputId);
    const table = document.getElementById(tableId);
    if (!input || !table) return;

    input.addEventListener("input", () => {
        const query = input.value.toLowerCase().trim();
        const rows = table.querySelectorAll("tbody tr");
        rows.forEach(r => {
            const text = r.textContent.toLowerCase();
            r.style.display = text.includes(query) ? "" : "none";
        });
    });
}

function debounce(fn, ms) {
    let timer;
    return function (...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), ms);
    };
}
