/**
 * Smart Campus Analytics - Centralized API Service
 */

const API_BASE = "";

function formatApiError(errData, fallback) {
    const detail = errData?.detail;
    if (typeof detail === "string") {
        return detail;
    }
    if (detail && typeof detail === "object") {
        const messages = [detail.message];
        if (detail.errors && typeof detail.errors === "object") {
            Object.values(detail.errors).forEach(value => {
                messages.push(...(Array.isArray(value) ? value : [value]));
            });
        }
        if (detail.counts && typeof detail.counts === "object") {
            const counts = detail.counts;
            messages.push(
                `Accepted: ${counts.accepted_rows || 0}; rejected: ${counts.rejected_rows || 0}; ` +
                `duplicates: ${counts.duplicate_rows || 0}; updated: ${counts.updated_rows || 0}.`
            );
        }
        const message = messages.filter(value => typeof value === "string" && value).join(" ");
        if (message) {
            return message;
        }
    }
    return fallback;
}

function readStoredUser() {
    try {
        return JSON.parse(localStorage.getItem("user") || "null");
    } catch {
        localStorage.removeItem("user");
        return null;
    }
}

export const authState = {
    token: localStorage.getItem("token") || null,
    user: readStoredUser()
};
const activeRequests = new Set();

export async function apiRequest(endpoint, options = {}) {
    const headers = options.headers || {};
    
    if (authState.token && !headers["Authorization"]) {
        headers["Authorization"] = `Bearer ${authState.token}`;
    }

    if (!(options.body instanceof FormData) && !headers["Content-Type"]) {
        headers["Content-Type"] = "application/json";
    }

    const requestController = new AbortController();
    const config = {
        ...options,
        headers,
        signal: options.signal || requestController.signal
    };
    if (!options.signal) activeRequests.add(requestController);

    try {
        const response = await fetch(`${API_BASE}${endpoint}`, config);
        
        if (response.status === 401 && endpoint !== "/api/auth/login") {
            logout({ revoke: false });
            throw new Error("Session expired. Please sign in again.");
        }

        if (response.status === 403) {
            const errData = await response.json().catch(() => ({}));
            const error = new Error(formatApiError(errData, "Access forbidden for your user role."));
            error.status = response.status;
            error.detail = errData.detail;
            throw error;
        }

        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            const error = new Error(formatApiError(errData, `Request failed with status ${response.status}`));
            error.status = response.status;
            error.detail = errData.detail;
            throw error;
        }

        const contentType = response.headers.get("content-type");
        if (contentType && contentType.includes("application/json")) {
            return await response.json();
        }
        return response;
    } catch (err) {
        console.error(`API Error on [${endpoint}]:`, err);
        throw err;
    } finally {
        activeRequests.delete(requestController);
    }
}

export async function login(username, password) {
    const data = await apiRequest("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password })
    });
    
    authState.token = data.access_token;
    authState.user = {
        username: data.username,
        role: data.role,
        name: data.name,
        student_id: data.student_id
    };

    localStorage.setItem("token", authState.token);
    localStorage.setItem("user", JSON.stringify(authState.user));
    return authState.user;
}

export function getCurrentUser() {
    return apiRequest("/api/auth/me");
}

export function requestStudentAccount(studentId, password) {
    return requestAccount({ role: "STUDENT", student_id: studentId, password });
}

export function requestAccount(accountRequest) {
    return apiRequest("/api/auth/account-requests", {
        method: "POST",
        body: JSON.stringify(accountRequest)
    });
}

export function logout({ revoke = true } = {}) {
    const token = authState.token;
    authState.token = null;
    authState.user = null;
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    activeRequests.forEach(controller => controller.abort());
    activeRequests.clear();
    window.dispatchEvent(new Event("educare:session-ended"));

    if (revoke && token) {
        fetch(`${API_BASE}/api/auth/logout`, {
            method: "POST",
            headers: { Authorization: `Bearer ${token}` }
        }).catch(error => console.error("Could not revoke the signed-out session:", error));
    }
}

// Students API
export function getStudents(params = {}) {
    const qs = new URLSearchParams(params).toString();
    return apiRequest(`/api/students?${qs}`);
}

export function getStudentProfile(studentId) {
    return apiRequest(`/api/students/${studentId}`);
}

export function sendStudentMessage(studentId, message) {
    return apiRequest(`/api/students/${studentId}/message`, {
        method: "POST",
        body: JSON.stringify({ message })
    });
}

export function getStudentMessages(studentId) {
    return apiRequest(`/api/students/${studentId}/messages`);
}

export function getMessageInbox() {
    return apiRequest("/api/students/messages/inbox");
}

export function replyStudentMessage(messageId, reply) {
    return apiRequest(`/api/students/messages/${messageId}/reply`, {
        method: "PATCH",
        body: JSON.stringify({ reply })
    });
}

// Analytics API
export function getOverview(params = {}) {
    const qs = new URLSearchParams(params).toString();
    return apiRequest(`/api/analytics/overview?${qs}`);
}

export function getTrends(params = {}) {
    const qs = new URLSearchParams(params).toString();
    return apiRequest(`/api/analytics/trends?${qs}`);
}

export function getSegments() {
    return apiRequest("/api/analytics/segments");
}

export function getInsights() {
    return apiRequest("/api/analytics/insights");
}

export function searchAnalytics(query) {
    return apiRequest(`/api/analytics/search?q=${encodeURIComponent(query)}`);
}

// Interventions API
export function getInterventions(params = {}) {
    const qs = new URLSearchParams(params).toString();
    return apiRequest(`/api/interventions?${qs}`);
}

export function updateIntervention(actionId, status, notes = null) {
    const body = { status };
    if (notes !== null) body.notes = notes;
    return apiRequest(`/api/interventions/${actionId}`, {
        method: "PATCH",
        body: JSON.stringify(body)
    });
}

// Admin API
export function getScoreSettings() {
    return apiRequest("/api/admin/settings");
}

export function updateScoreSettings(settings) {
    return apiRequest("/api/admin/settings", {
        method: "POST",
        body: JSON.stringify(settings)
    });
}

export function recomputeAnalytics() {
    return apiRequest("/api/admin/recompute", {
        method: "POST"
    });
}

export function getDataQualityLog() {
    return apiRequest("/api/admin/quality-log");
}

export function getModelMetrics() {
    return apiRequest("/api/admin/model-metrics");
}

export function getStudentAccountRequests() {
    return getAccountRequests();
}

export function reviewStudentAccountRequest(requestId, decision) {
    return reviewAccountRequest(requestId, decision);
}

export function getAccountRequests(filters = {}) {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
        if (value) params.set(key, value);
    });
    const query = params.toString();
    return apiRequest(`/api/admin/account-requests${query ? `?${query}` : ""}`);
}

export function getAccountRequestCount() {
    return apiRequest("/api/admin/account-requests/count");
}

export function reviewAccountRequest(requestId, decision, reason) {
    return apiRequest(`/api/admin/account-requests/${requestId}/${decision}`, {
        method: "POST",
        ...(decision === "reject" ? { body: JSON.stringify({ reason: reason || null }) } : {})
    });
}

export function uploadCsvFiles(formData) {
    return apiRequest("/api/admin/upload", {
        method: "POST",
        body: formData
    });
}

// LLM API
export function getExplain(studentId) {
    return apiRequest("/api/explain", {
        method: "POST",
        body: JSON.stringify({ student_id: studentId })
    });
}

export function askCampusAI(query) {
    return apiRequest("/api/ask", {
        method: "POST",
        body: JSON.stringify({ query })
    });
}
