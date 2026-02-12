"use client";

import { useEffect, useMemo, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api";
const SESSION_STORAGE_KEY = "linkedin_cv_session_id";

const I18N = {
  es: {
    title: "SeekJob",
    subtitle: "Sube CV, revisa análisis IA y prioriza ofertas por mejor encaje.",
    tabA: "Buscador",
    tabB: "Sesiones previas",
    tabC: "Análisis IA del perfil",
    tabD: "Búsqueda | Resultados",
    upload: "Subir CV",
    summary: "Resumen del CV",
    analysis: "Análisis IA del perfil",
    strategy: "Estrategia de búsqueda",
    loadStrategy: "Actualizar estrategia",
    search: "Búsqueda",
    portals: "Portales permitidos",
    results: "Resultados",
    scheduler: "Segundo plano",
    runSearch: "Buscar ahora",
    saveSummary: "Confirmar resumen",
    reanalyze: "Reanalizar IA",
    recommendedQueries: "Consultas recomendadas",
    activeQueries: "Consultas activas (se aplican en la búsqueda)",
    addQuery: "Agregar consulta",
    queryPlaceholder: "Escribe una consulta y agrégala",
    enabledQueries: "Consultas habilitadas",
    remove: "Quitar",
    selectAll: "Seleccionar todos",
    deselectAll: "Deseleccionar todos",
    deleteSelected: "Borrar seleccionadas",
    clearResults: "Limpiar resultados",
    addToSearch: "Agregar",
    strategyDeleteSelected: "Borrar seleccionadas",
    source: "Fuente",
    page: "Página",
    of: "de",
    total: "Total",
    pageSize: "Tamaño de página",
    prev: "Anterior",
    next: "Siguiente",
    sessionHistory: "Sesiones previas",
    fileName: "Archivo",
    analysisAt: "Análisis ejecutado",
    createdAt: "Sesión creada",
    status: "Estado",
    resume: "Retomar",
    candidateName: "Nombre CV",
    deleteSession: "Borrar",
    processSession: "Procesar",
    deleteDatabase: "Borrar BD",
    insights: "Feedback IA",
    generateInsights: "Generar feedback",
    refreshInsights: "Actualizar feedback",
    insightStatus: "Estado feedback",
    insightNoData: "Sin feedback generado todavía.",
  },
  en: {
    title: "SeekJob",
    subtitle: "Upload CV, review AI analysis, and prioritize jobs by best fit.",
    tabA: "Buscador",
    tabB: "Previous sessions",
    tabC: "AI profile analysis",
    tabD: "Search | Results",
    upload: "Upload CV",
    summary: "CV Summary",
    analysis: "AI Profile Analysis",
    strategy: "Search strategy",
    loadStrategy: "Refresh strategy",
    search: "Search",
    portals: "Allowed portals",
    results: "Results",
    scheduler: "Background",
    runSearch: "Search now",
    saveSummary: "Confirm summary",
    reanalyze: "Reanalyze AI",
    recommendedQueries: "Recommended queries",
    activeQueries: "Active queries (used in search)",
    addQuery: "Add query",
    queryPlaceholder: "Type a query and add it",
    enabledQueries: "Enabled queries",
    remove: "Remove",
    selectAll: "Select all",
    deselectAll: "Deselect all",
    deleteSelected: "Delete selected",
    clearResults: "Clear results",
    addToSearch: "Add",
    strategyDeleteSelected: "Delete selected",
    source: "Source",
    page: "Page",
    of: "of",
    total: "Total",
    pageSize: "Page size",
    prev: "Prev",
    next: "Next",
    sessionHistory: "Session history",
    fileName: "File",
    analysisAt: "Analysis run",
    createdAt: "Session created",
    status: "Status",
    resume: "Resume",
    candidateName: "CV name",
    deleteSession: "Delete",
    processSession: "Process",
    deleteDatabase: "Delete DB",
    insights: "AI Feedback",
    generateInsights: "Generate feedback",
    refreshInsights: "Refresh feedback",
    insightStatus: "Feedback status",
    insightNoData: "No feedback generated yet.",
  },
};

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    cache: "no-store",
    ...options,
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // keep fallback
    }
    throw new Error(detail);
  }
  return response.json();
}

function listToCsv(arr) {
  return (arr || []).join(", ");
}

function listToLines(arr) {
  return (arr || []).join("\n");
}

function csvToList(value) {
  return String(value || "")
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
}

function linesToList(value) {
  return String(value || "")
    .split(/\n|;/)
    .map((v) => v.trim())
    .filter(Boolean);
}

function uniqueList(values) {
  const seen = new Set();
  const out = [];
  for (const value of values || []) {
    const cleaned = String(value || "").trim();
    if (!cleaned) continue;
    const key = cleaned.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(cleaned);
  }
  return out;
}

function normalizeQuery(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeQueryKey(value) {
  return normalizeQuery(value).toLowerCase();
}

function normalizeDismissedSuggestionKeys(values) {
  const seen = new Set();
  const out = [];
  for (const value of values || []) {
    const key = normalizeQueryKey(value);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(key);
  }
  return out;
}

function filterDismissedSuggestions(items, dismissedKeys) {
  const blocked = new Set(normalizeDismissedSuggestionKeys(dismissedKeys || []));
  if (blocked.size === 0) return items || [];
  return (items || []).filter((item) => {
    const key = normalizeQueryKey(item?.text || item);
    return key && !blocked.has(key);
  });
}

function makeQueryId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `q_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 9)}`;
}

function mergeQueryItems(existing, incoming, options = {}) {
  const enabled = options.enabled ?? true;
  const source = options.source || "manual";
  const byKey = new Map();

  for (const item of existing || []) {
    const text = normalizeQuery(item?.text || item);
    if (!text) continue;
    byKey.set(text.toLowerCase(), {
      id: item?.id || makeQueryId(),
      text,
      enabled: item?.enabled !== false,
      source: item?.source || source,
    });
  }

  for (const value of incoming || []) {
    const text = normalizeQuery(value?.text || value);
    if (!text) continue;
    const key = text.toLowerCase();
    if (byKey.has(key)) continue;
    byKey.set(key, { id: value?.id || makeQueryId(), text, enabled, source });
  }

  return Array.from(byKey.values());
}

function mergeSuggestionItems(existing, incoming, options = {}) {
  const source = options.source || "analysis";
  const byKey = new Map();

  for (const item of existing || []) {
    const text = normalizeQuery(item?.text || item);
    if (!text) continue;
    byKey.set(text.toLowerCase(), {
      id: item?.id || makeQueryId(),
      text,
      selected: item?.selected !== false,
      source: item?.source || source,
    });
  }

  for (const value of incoming || []) {
    const text = normalizeQuery(value?.text || value);
    if (!text) continue;
    const key = text.toLowerCase();
    if (byKey.has(key)) continue;
    byKey.set(key, {
      id: value?.id || makeQueryId(),
      text,
      selected: value?.selected !== false,
      source,
    });
  }

  return Array.from(byKey.values());
}

function activeQueryList(items) {
  const enabledItems = (items || [])
    .filter((item) => item?.enabled !== false)
    .map((item) => item?.text || "");
  return uniqueList(enabledItems);
}

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function normalizeSourceSelection(values, available = []) {
  const allowed = new Set(
    (available || [])
      .filter((item) => item?.enabled !== false)
      .map((item) => item?.source_id)
      .filter(Boolean),
  );
  const out = [];
  const seen = new Set();
  for (const value of values || []) {
    const sourceId = String(value || "").trim();
    if (!sourceId) continue;
    if (allowed.size > 0 && !allowed.has(sourceId)) continue;
    if (seen.has(sourceId)) continue;
    seen.add(sourceId);
    out.push(sourceId);
  }
  if (out.length === 0 && available.length > 0) {
    const firstEnabled = (available || []).find((item) => item?.enabled !== false && item?.source_id);
    return firstEnabled ? [firstEnabled.source_id] : [];
  }
  return out;
}

export default function Home() {
  const [lang, setLang] = useState("es");
  const t = I18N[lang];
  const [activeTab, setActiveTab] = useState("a");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const [file, setFile] = useState(null);
  const [cvId, setCvId] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [sessionHistory, setSessionHistory] = useState([]);
  const [selectedHistorySessionIds, setSelectedHistorySessionIds] = useState([]);
  const [restoringSession, setRestoringSession] = useState(false);

  const [summary, setSummary] = useState({
    highlights: [],
    skills: [],
    experience: [],
    education: [],
    languages: [],
  });

  const [analysis, setAnalysis] = useState({
    target_roles: [],
    secondary_roles: [],
    seniority: "unknown",
    industries: [],
    strengths: [],
    skill_gaps: [],
    recommended_queries: [],
    llm_status: "fallback",
    llm_error: null,
  });

  const [strategy, setStrategy] = useState({
    role_focus: [],
    recommended_queries: [],
    market_roles: [],
  });

  const [searchId, setSearchId] = useState("");
  const [country, setCountry] = useState("");
  const [city, setCity] = useState("");
  const [timeWindow, setTimeWindow] = useState("24");
  const [availableSources, setAvailableSources] = useState([]);
  const [selectedSources, setSelectedSources] = useState(["linkedin_public"]);
  const [queryItems, setQueryItems] = useState([]);
  const [suggestedQueries, setSuggestedQueries] = useState([]);
  const [dismissedSuggestedQueries, setDismissedSuggestedQueries] = useState([]);
  const [newQuery, setNewQuery] = useState("");

  const [sortBy, setSortBy] = useState("newest");
  const [sourceFilter, setSourceFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [subcategoryFilter, setSubcategoryFilter] = useState("");
  const [maxPostedHours, setMaxPostedHours] = useState("");
  const [locationContains, setLocationContains] = useState("");

  const [results, setResults] = useState([]);
  const [resultsMeta, setResultsMeta] = useState({
    total: 0,
    page: 1,
    page_size: 50,
    total_pages: 0,
    has_prev: false,
    has_next: false,
  });
  const [resultsPage, setResultsPage] = useState(1);
  const [resultsPageSize, setResultsPageSize] = useState("50");
  const [facets, setFacets] = useState({
    sources: {},
    categories: {},
    subcategories: {},
    modalities: {},
    locations: {},
    posted_buckets: {},
  });
  const [scheduler, setScheduler] = useState({ is_running: false, interval_minutes: 60, last_tick_at: null });
  const [latestInsight, setLatestInsight] = useState(null);

  const summaryText = useMemo(
    () => ({
      highlights: listToLines(summary.highlights),
      skills: listToLines(summary.skills),
      experience: listToLines(summary.experience),
      education: listToLines(summary.education),
      languages: listToLines(summary.languages),
    }),
    [summary],
  );

  const run = async (fn) => {
    setError("");
    setBusy(true);
    try {
      await fn();
    } catch (err) {
      setError(err.message || "Operation failed");
    } finally {
      setBusy(false);
    }
  };

  const refreshScheduler = async () => {
    const status = await api("/scheduler/status");
    setScheduler(status);
  };

  const refreshSessionHistory = async () => {
    const out = await api("/session/history?limit=50");
    setSessionHistory(out.items || []);
  };

  const refreshSources = async () => {
    const out = await api("/searches/sources");
    const items = Array.isArray(out) ? out : [];
    setAvailableSources(items);
    setSelectedSources((prev) => normalizeSourceSelection(prev, items));
  };

  const loadSessionSnapshot = async (session) => {
    if (!session) return;

    const sessionUiState = session.ui_state || {};
    const sessionDismissedKeys = normalizeDismissedSuggestionKeys(sessionUiState.dismissed_suggested_queries || []);

    setSessionId(session.session_id || "");
    setCvId(session.cv_id || "");
    setSearchId(session.active_search_id || "");
    setDismissedSuggestedQueries(sessionDismissedKeys);
    applyUiState(sessionUiState);

    if (session.cv_id) {
      const summaryOut = await api(`/cv/${session.cv_id}/summary`);
      setSummary(summaryOut.summary || summary);
      setAnalysis(summaryOut.analysis || analysis);
      setSuggestedQueries((prev) =>
        filterDismissedSuggestions(
          mergeSuggestionItems(prev, summaryOut.analysis?.recommended_queries || [], { source: "analysis" }),
          sessionDismissedKeys,
        ),
      );
      await refreshStrategy(session.cv_id, sessionDismissedKeys);
      await refreshLatestInsight(session.cv_id);
    }

    if (session.active_search_id) {
      try {
        const searchOut = await api(`/searches/${session.active_search_id}`);
        setSelectedSources((prev) =>
          normalizeSourceSelection(searchOut?.sources?.length ? searchOut.sources : prev, availableSources),
        );
      } catch {
        // noop
      }
      await refreshResults(session.active_search_id);
      await refreshFacets(session.active_search_id);
    } else {
      setResults([]);
      setFacets({
        sources: {},
        categories: {},
        subcategories: {},
        modalities: {},
        locations: {},
        posted_buckets: {},
      });
    }
  };

  const refreshStrategy = async (targetCvId = cvId, dismissedKeys = dismissedSuggestedQueries) => {
    if (!targetCvId) return;
    const out = await api(`/cv/${targetCvId}/strategy`);
    setStrategy(out);
    setSuggestedQueries((prev) =>
      filterDismissedSuggestions(
        mergeSuggestionItems(prev, out.recommended_queries || [], { source: "strategy" }),
        dismissedKeys,
      ),
    );
  };

  const buildResultsPath = (targetSearchId) => {
    const params = new URLSearchParams();
    params.set("sort_by", sortBy);
    if (sourceFilter) params.set("source", sourceFilter);
    if (categoryFilter) params.set("category", categoryFilter);
    if (subcategoryFilter) params.set("subcategory", subcategoryFilter);
    if (maxPostedHours) params.set("max_posted_hours", maxPostedHours);
    if (locationContains) params.set("location_contains", locationContains);
    params.set("page", String(resultsPage));
    params.set("page_size", String(Number(resultsPageSize) || 50));
    return `/searches/${targetSearchId}/results?${params.toString()}`;
  };

  const refreshResults = async (targetSearchId = searchId) => {
    if (!targetSearchId) return;
    const data = await api(buildResultsPath(targetSearchId));
    setResults(data.items || []);
    setResultsMeta({
      total: data.total || 0,
      page: data.page || 1,
      page_size: data.page_size || Number(resultsPageSize) || 50,
      total_pages: data.total_pages || 0,
      has_prev: Boolean(data.has_prev),
      has_next: Boolean(data.has_next),
    });
  };

  const refreshFacets = async (targetSearchId = searchId) => {
    if (!targetSearchId) return;
    const data = await api(`/searches/${targetSearchId}/facets`);
    setFacets(data);
  };

  const logInteraction = async (payload) => {
    if (!payload || !payload.cv_id) return;
    try {
      await api("/interactions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch {
      // non-blocking telemetry
    }
  };

  const refreshLatestInsight = async (targetCvId = cvId) => {
    if (!targetCvId) {
      setLatestInsight(null);
      return;
    }
    const out = await api(`/insights/cv/${targetCvId}/latest`);
    setLatestInsight(out || null);
  };

  const applyUiState = (uiState) => {
    if (!uiState || typeof uiState !== "object") return;

    const dismissedKeys = Array.isArray(uiState.dismissed_suggested_queries)
      ? normalizeDismissedSuggestionKeys(uiState.dismissed_suggested_queries)
      : dismissedSuggestedQueries;

    if (typeof uiState.country === "string") setCountry(uiState.country);
    if (typeof uiState.city === "string") setCity(uiState.city);
    if (uiState.time_window_hours != null) setTimeWindow(String(uiState.time_window_hours));
    if (typeof uiState.sort_by === "string") setSortBy(uiState.sort_by);
    if (typeof uiState.source === "string") setSourceFilter(uiState.source);
    if (typeof uiState.category === "string") setCategoryFilter(uiState.category);
    if (typeof uiState.subcategory === "string") setSubcategoryFilter(uiState.subcategory);
    if (typeof uiState.max_posted_hours === "string") setMaxPostedHours(uiState.max_posted_hours);
    if (typeof uiState.location_contains === "string") setLocationContains(uiState.location_contains);
    if (uiState.page != null) setResultsPage(Math.max(1, Number(uiState.page) || 1));
    if (uiState.page_size != null) setResultsPageSize(String(Number(uiState.page_size) || 50));
    if (typeof uiState.lang === "string" && (uiState.lang === "es" || uiState.lang === "en")) setLang(uiState.lang);
    if (Array.isArray(uiState.dismissed_suggested_queries)) {
      setDismissedSuggestedQueries(dismissedKeys);
    }
    if (Array.isArray(uiState.query_items)) {
      setQueryItems(mergeQueryItems([], uiState.query_items, { enabled: true, source: "session" }));
    }
    if (Array.isArray(uiState.sources)) {
      setSelectedSources(normalizeSourceSelection(uiState.sources, availableSources));
    }
    if (Array.isArray(uiState.suggested_queries)) {
      setSuggestedQueries(
        filterDismissedSuggestions(
          mergeSuggestionItems([], uiState.suggested_queries, { source: "session" }),
          dismissedKeys,
        ),
      );
    }
    if (typeof uiState.search_id === "string") setSearchId(uiState.search_id);
  };

  useEffect(() => {
    refreshScheduler().catch(() => null);
    refreshSessionHistory().catch(() => null);
    refreshSources().catch(() => null);
  }, []);


  useEffect(() => {
    setSelectedHistorySessionIds((prev) =>
      prev.filter((id) => (sessionHistory || []).some((item) => item.session_id === id)),
    );
  }, [sessionHistory]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      let storedSessionId = "";
      try {
        storedSessionId = localStorage.getItem(SESSION_STORAGE_KEY) || "";
      } catch {
        storedSessionId = "";
      }
      if (!storedSessionId) return;

      setRestoringSession(true);
      try {
        const out = await api(`/session/current?session_id=${encodeURIComponent(storedSessionId)}`);
        const session = out?.session;
        if (!session) {
          localStorage.removeItem(SESSION_STORAGE_KEY);
          return;
        }
        if (cancelled) return;

        await loadSessionSnapshot(session);
      } catch {
        // noop
      } finally {
        if (!cancelled) setRestoringSession(false);
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!sessionId) return;
    try {
      localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
    } catch {
      // noop
    }
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId || restoringSession) return;

    const payload = {
      session_id: sessionId,
      active_search_id: searchId || null,
      ui_state: {
        cv_id: cvId || null,
        search_id: searchId || null,
        country,
        city,
        time_window_hours: Number(timeWindow) || 24,
        sources: selectedSources,
        query_items: queryItems,
        suggested_queries: suggestedQueries,
        dismissed_suggested_queries: dismissedSuggestedQueries,
        sort_by: sortBy,
        source: sourceFilter,
        category: categoryFilter,
        subcategory: subcategoryFilter,
        max_posted_hours: maxPostedHours,
        location_contains: locationContains,
        page: resultsPage,
        page_size: Number(resultsPageSize) || 50,
        lang,
      },
    };

    const timer = setTimeout(() => {
      api("/session/state", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).catch(() => null);
    }, 400);

    return () => clearTimeout(timer);
  }, [
    sessionId,
    restoringSession,
    cvId,
    searchId,
    country,
    city,
    timeWindow,
    selectedSources,
    queryItems,
    suggestedQueries,
    dismissedSuggestedQueries,
    sortBy,
    sourceFilter,
    categoryFilter,
    subcategoryFilter,
    maxPostedHours,
    locationContains,
    resultsPage,
    resultsPageSize,
    lang,
  ]);

  useEffect(() => {
    if (!searchId) return;
    refreshResults(searchId).catch(() => null);
  }, [searchId, sortBy, sourceFilter, categoryFilter, subcategoryFilter, maxPostedHours, locationContains, resultsPage, resultsPageSize]);

  useEffect(() => {
    if (!searchId) return;
    const id = setInterval(() => {
      refreshResults(searchId).catch(() => null);
      refreshScheduler().catch(() => null);
      refreshFacets(searchId).catch(() => null);
    }, 30000);
    return () => clearInterval(id);
  }, [searchId, sortBy, sourceFilter, categoryFilter, subcategoryFilter, maxPostedHours, locationContains, resultsPage, resultsPageSize]);

  useEffect(() => {
    if (resultsMeta.total_pages > 0 && resultsPage > resultsMeta.total_pages) {
      setResultsPage(resultsMeta.total_pages);
    }
  }, [resultsMeta.total_pages, resultsPage]);

  const uploadCv = () =>
    run(async () => {
      if (!file) throw new Error("Select a CV file");

      const formData = new FormData();
      formData.append("file", file);

      const out = await api("/cv/upload", { method: "POST", body: formData });
      setSessionId(out.session_id || "");
      setCvId(out.cv_id);
      setSummary(out.summary);
      setAnalysis(out.analysis || analysis);
      setSearchId("");
      setQueryItems([]);
      setDismissedSuggestedQueries([]);
      setSuggestedQueries(
        filterDismissedSuggestions(
          mergeSuggestionItems([], out.analysis?.recommended_queries || [], { source: "analysis" }),
          [],
        ),
      );

      await refreshStrategy(out.cv_id, []);
      await refreshLatestInsight(out.cv_id);
      await refreshSessionHistory();
    });

  const saveSummary = () =>
    run(async () => {
      if (!cvId) throw new Error("Upload CV first");

      const payload = {
        summary: {
          highlights: linesToList(summaryText.highlights),
          skills: linesToList(summaryText.skills),
          experience: linesToList(summaryText.experience),
          education: linesToList(summaryText.education),
          languages: linesToList(summaryText.languages),
        },
      };

      const out = await api(`/cv/${cvId}/summary`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setSummary(out.summary);
      setAnalysis(out.analysis || analysis);
      setSuggestedQueries((prev) =>
        filterDismissedSuggestions(
          mergeSuggestionItems(prev, out.analysis?.recommended_queries || [], { source: "analysis" }),
          dismissedSuggestedQueries,
        ),
      );
      await refreshStrategy(cvId, dismissedSuggestedQueries);
    });

  const reanalyze = () =>
    run(async () => {
      if (!cvId) throw new Error("Upload CV first");
      const out = await api(`/cv/${cvId}/analyze`, { method: "POST" });
      setSummary(out.summary);
      setAnalysis(out.analysis || analysis);
      setSuggestedQueries((prev) =>
        filterDismissedSuggestions(
          mergeSuggestionItems(prev, out.analysis?.recommended_queries || [], { source: "analysis" }),
          dismissedSuggestedQueries,
        ),
      );
      await refreshStrategy(cvId, dismissedSuggestedQueries);
      await refreshLatestInsight(cvId);
    });

  const generateInsight = () =>
    run(async () => {
      if (!cvId) throw new Error("Upload CV first");
      const out = await api(`/insights/cv/${cvId}/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ days: 7 }),
      });
      setLatestInsight(out || null);
    });

  const createSearch = () =>
    run(async () => {
      if (!cvId) throw new Error("Upload and confirm CV first");
      if (selectedSources.length === 0) throw new Error("Select at least one source");
      const enabledKeywords = activeQueryList(queryItems);
      if (enabledKeywords.length === 0) {
        throw new Error("Add at least one enabled query");
      }

      const out = await api("/searches", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cv_id: cvId,
          country: country || null,
          city: city || null,
          time_window_hours: Number(timeWindow),
          keywords: enabledKeywords,
          sources: selectedSources,
        }),
      });

      setSearchId(out.search_id);
      setResults(out.results?.items || []);
      setResultsPage(1);
      await refreshScheduler();
      await refreshFacets(out.search_id);
    });

  const rerunSearch = () =>
    run(async () => {
      if (!searchId) throw new Error("Create search first");
      if (selectedSources.length === 0) throw new Error("Select at least one source");
      const enabledKeywords = activeQueryList(queryItems);
      if (enabledKeywords.length === 0) {
        throw new Error("Add at least one enabled query");
      }
      await api(`/searches/${searchId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          country: country || null,
          city: city || null,
          time_window_hours: Number(timeWindow),
          keywords: enabledKeywords,
          sources: selectedSources,
        }),
      });
      await api(`/searches/${searchId}/run`, { method: "POST" });
      setResultsPage(1);
      await refreshResults(searchId);
      await refreshFacets(searchId);
    });

  const setChecked = (row, checked) =>
    run(async () => {
      await api(`/searches/results/${row.result_id}/check`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ checked }),
      });
      await logInteraction({
        cv_id: cvId,
        session_id: sessionId || null,
        search_id: searchId || null,
        result_id: row.result_id,
        job_id: row.job_id,
        event_type: checked ? "check" : "uncheck",
        meta: {
          title: row.title,
          source: row.source,
        },
      });
      await refreshResults(searchId);
    });

  const setAllResultsChecked = (checked) =>
    run(async () => {
      if (!searchId) throw new Error("Create search first");
      if (results.length === 0) return;
      await Promise.all(
        results.map((row) =>
          api(`/searches/results/${row.result_id}/check`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ checked }),
          }),
        ),
      );
      await logInteraction({
        cv_id: cvId,
        session_id: sessionId || null,
        search_id: searchId || null,
        event_type: checked ? "bulk_check" : "bulk_uncheck",
        meta: {
          count: results.length,
        },
      });
      await refreshResults(searchId);
    });

  const clearSearchResults = () =>
    run(async () => {
      if (!searchId) throw new Error("Create search first");
      await api(`/searches/${searchId}/results`, { method: "DELETE" });
      setResults([]);
      setResultsMeta({
        total: 0,
        page: 1,
        page_size: Number(resultsPageSize) || 50,
        total_pages: 0,
        has_prev: false,
        has_next: false,
      });
      setResultsPage(1);
      await refreshFacets(searchId);
    });

  const startScheduler = () =>
    run(async () => {
      const out = await api("/scheduler/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ interval_minutes: 60 }),
      });
      setScheduler(out);
    });

  const stopScheduler = () =>
    run(async () => {
      const out = await api("/scheduler/stop", { method: "POST" });
      setScheduler(out);
    });

  const resetCurrentSessionState = () => {
    setSessionId("");
    setCvId("");
    setSearchId("");
    setResults([]);
    setStrategy({
      role_focus: [],
      recommended_queries: [],
      market_roles: [],
    });
    setQueryItems([]);
    setSuggestedQueries([]);
    setDismissedSuggestedQueries([]);
    setSummary({
      highlights: [],
      skills: [],
      experience: [],
      education: [],
      languages: [],
    });
    setAnalysis({
      target_roles: [],
      secondary_roles: [],
      seniority: "unknown",
      industries: [],
      strengths: [],
      skill_gaps: [],
      recommended_queries: [],
      llm_status: "fallback",
      llm_error: null,
    });
    setSelectedHistorySessionIds([]);
    setLatestInsight(null);
    try {
      localStorage.removeItem(SESSION_STORAGE_KEY);
    } catch {
      // noop
    }
  };

  const toggleHistorySelection = (targetSessionId, enabled) => {
    const cleanId = String(targetSessionId || "").trim();
    if (!cleanId) return;
    setSelectedHistorySessionIds((prev) => {
      const has = prev.includes(cleanId);
      if (enabled && !has) return [...prev, cleanId];
      if (!enabled && has) return prev.filter((item) => item !== cleanId);
      return prev;
    });
  };

  const resumeSessionById = async (targetSessionId) => {
    if (!targetSessionId) return;
    const resumed = await api("/session/resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: targetSessionId }),
    });
    await loadSessionSnapshot(resumed);
    await refreshSessionHistory();
  };

  const deleteSessionById = async (targetSessionId, options = {}) => {
    const refresh = options.refresh ?? true;
    if (!targetSessionId) return;
    await api(`/session/${targetSessionId}`, { method: "DELETE" });
    if (targetSessionId === sessionId) {
      resetCurrentSessionState();
    }
    if (refresh) {
      await refreshSessionHistory();
    }
  };

  const processSelectedHistory = () =>
    run(async () => {
      const selected = [...selectedHistorySessionIds];
      if (selected.length === 0) {
        throw new Error("Selecciona una sesión para procesar");
      }
      if (selected.length > 1) {
        throw new Error("Selecciona solo una sesión para procesar");
      }
      await resumeSessionById(selected[0]);
    });

  const deleteSelectedHistory = () =>
    run(async () => {
      const selected = [...new Set(selectedHistorySessionIds)];
      if (selected.length === 0) {
        throw new Error("Selecciona al menos una sesión para borrar");
      }

      for (const targetSessionId of selected) {
        await deleteSessionById(targetSessionId, { refresh: false });
      }
      setSelectedHistorySessionIds([]);
      await refreshSessionHistory();
    });

  const purgeDatabaseKeepingCurrent = () =>
    run(async () => {
      const out = await api("/session/purge-db", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keep_session_id: sessionId || null }),
      });

      setSelectedHistorySessionIds([]);
      await refreshSessionHistory();

      if (!out?.kept_session_id) {
        resetCurrentSessionState();
        return;
      }

      if (out.kept_session_id !== sessionId) {
        const currentOut = await api(`/session/current?session_id=${encodeURIComponent(out.kept_session_id)}`);
        if (currentOut?.session) {
          await loadSessionSnapshot(currentOut.session);
        } else {
          resetCurrentSessionState();
        }
        return;
      }

      if (searchId) {
        await refreshResults(searchId);
        await refreshFacets(searchId);
      }
    });

  const toggleSearchSource = (sourceId, enabled) => {
    const cleanId = String(sourceId || "").trim();
    if (!cleanId) return;
    setSelectedSources((prev) => {
      const has = prev.includes(cleanId);
      if (enabled && !has) return [...prev, cleanId];
      if (!enabled && has) return prev.filter((item) => item !== cleanId);
      return prev;
    });
  };

  const selectAllSources = () => {
    setSelectedSources(
      (availableSources || [])
        .filter((item) => item?.enabled !== false)
        .map((item) => item.source_id)
        .filter(Boolean),
    );
  };

  const deselectAllSources = () => {
    setSelectedSources([]);
  };

  const updateSuggestedQuery = (index, value) => {
    const next = [...suggestedQueries];
    if (!next[index]) return;
    next[index] = { ...next[index], text: value };
    setSuggestedQueries(next);
  };

  const toggleSuggestedQuery = (index, selected) => {
    const next = [...suggestedQueries];
    if (!next[index]) return;
    next[index] = { ...next[index], selected };
    setSuggestedQueries(next);
  };

  const addSelectedSuggestedQueries = () => {
    const selected = (suggestedQueries || [])
      .filter((item) => item?.selected !== false)
      .map((item) => normalizeQuery(item?.text))
      .filter(Boolean);
    if (selected.length === 0) return;

    setQueryItems((prev) => mergeQueryItems(prev, selected, { enabled: true, source: "recommended" }));
  };

  const removeSelectedSuggestedQueries = () => {
    if (suggestedQueries.length === 0) return;

    const selectedKeys = normalizeDismissedSuggestionKeys(
      suggestedQueries
        .filter((item) => item?.selected !== false)
        .map((item) => item?.text),
    );
    if (selectedKeys.length === 0) return;

    setDismissedSuggestedQueries((prev) => normalizeDismissedSuggestionKeys([...prev, ...selectedKeys]));
    setSuggestedQueries((prev) =>
      prev.filter((item) => {
        if (item?.selected === false) return true;
        const key = normalizeQueryKey(item?.text);
        return !selectedKeys.includes(key);
      }),
    );
  };

  const addManualQuery = () => {
    const cleaned = normalizeQuery(newQuery);
    if (!cleaned) return;
    setQueryItems((prev) => mergeQueryItems(prev, [cleaned], { enabled: true, source: "manual" }));
    setNewQuery("");
  };

  const updateQueryItem = (index, value) => {
    const next = [...queryItems];
    if (!next[index]) return;
    next[index] = { ...next[index], text: value };
    setQueryItems(next);
  };

  const toggleQueryItem = (index, enabled) => {
    const next = [...queryItems];
    if (!next[index]) return;
    next[index] = { ...next[index], enabled };
    setQueryItems(next);
  };

  const setAllQueryItemsEnabled = (enabled) => {
    if (queryItems.length === 0) return;
    setQueryItems((prev) => prev.map((item) => ({ ...item, enabled })));
  };

  const removeQueryItem = (index) => {
    const next = [...queryItems];
    next.splice(index, 1);
    setQueryItems(next);
  };

  const removeSelectedQueryItems = () => {
    if (queryItems.length === 0) return;
    setQueryItems((prev) => prev.filter((item) => item?.enabled === false));
  };

  const enabledQueryCount = activeQueryList(queryItems).length;

  const sourceOptions = Object.keys(facets.sources || {}).sort();
  const categoryOptions = Object.keys(facets.categories || {}).sort();
  const subcategoryOptions = Object.keys(facets.subcategories || {}).sort();

  return (
    <main>
      <div className="card" style={{ marginBottom: 14 }}>
        <div className="row" style={{ alignItems: "center" }}>
          <div>
            <h1>{t.title}</h1>
            <p className="small">{t.subtitle}</p>
          </div>
          <div style={{ justifySelf: "end" }}>
            <button className="secondary" onClick={() => setLang(lang === "es" ? "en" : "es")}>ES / EN</button>
          </div>
        </div>
        {error ? <div className="alert">{error}</div> : null}
      </div>

      <div className="tabs" role="tablist" aria-label="Main app sections">
        <button
          type="button"
          className={`tab-button${activeTab === "a" ? " active" : ""}`}
          onClick={() => setActiveTab("a")}
        >
          {t.tabA}
        </button>
        <button
          type="button"
          className={`tab-button${activeTab === "b" ? " active" : ""}`}
          onClick={() => setActiveTab("b")}
        >
          {t.tabB}
        </button>
        <button
          type="button"
          className={`tab-button${activeTab === "c" ? " active" : ""}`}
          onClick={() => setActiveTab("c")}
        >
          {t.tabC}
        </button>
        <button
          type="button"
          className={`tab-button${activeTab === "d" ? " active" : ""}`}
          onClick={() => setActiveTab("d")}
        >
          {t.tabD}
        </button>
      </div>

      {activeTab === "a" ? <div className="grid two">
        <section className="card">
          <h2>{t.upload}</h2>
          <label>
            CV (.pdf / .docx)
            <input type="file" accept=".pdf,.docx" onChange={(e) => setFile(e.target.files?.[0] || null)} />
          </label>
          <div className="toolbar">
            <button onClick={uploadCv} disabled={busy || !file}>Upload</button>
            <span className="small">CV ID: {cvId || "-"}</span>
            <span className="small">Session ID: {sessionId || "-"}</span>
          </div>
        </section>

        <section className="card">
          <h2>{t.scheduler}</h2>
          <p className="small">
            Running: <strong>{scheduler.is_running ? "Yes" : "No"}</strong> | Interval: {scheduler.interval_minutes} min
          </p>
          <p className="small">Last tick: {scheduler.last_tick_at || "-"}</p>
          <div className="toolbar">
            <button onClick={startScheduler} disabled={busy}>Start</button>
            <button className="secondary" onClick={stopScheduler} disabled={busy}>Stop</button>
          </div>
        </section>
      </div> : null}

      {activeTab === "b" ? <section className="card" style={{ marginTop: 14 }}>
        <h2>{t.sessionHistory}</h2>
        <div className="toolbar" style={{ marginBottom: 10 }}>
          <button
            type="button"
            className="secondary"
            disabled={busy || selectedHistorySessionIds.length === 0 || selectedHistorySessionIds.length > 1}
            onClick={processSelectedHistory}
          >
            {t.processSession}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={busy || selectedHistorySessionIds.length === 0}
            onClick={deleteSelectedHistory}
          >
            {t.deleteSession}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={busy || !sessionId}
            onClick={purgeDatabaseKeepingCurrent}
          >
            {t.deleteDatabase}
          </button>
        </div>
        <div style={{ display: "grid", gap: 8 }}>
          {sessionHistory.length === 0 ? (
            <p className="small">No sessions yet.</p>
          ) : (
            sessionHistory.map((item) => (
              <div
                key={item.session_id}
                className="row"
                style={{
                  gridTemplateColumns: "auto 1fr 1fr 1fr 1fr",
                  gap: 8,
                  alignItems: "center",
                }}
              >
                <input
                  type="checkbox"
                  checked={selectedHistorySessionIds.includes(item.session_id)}
                  disabled={busy || !item.session_id}
                  onChange={(e) => toggleHistorySelection(item.session_id, e.target.checked)}
                />
                <div className="small">
                  <strong>{t.candidateName}:</strong> {item.candidate_name || "-"}
                </div>
                <div className="small">
                  <strong>{t.fileName}:</strong> {item.cv_filename || "-"}
                </div>
                <div className="small">
                  <strong>{t.analysisAt}:</strong> {formatDateTime(item.analysis_executed_at)}
                </div>
                <div className="small">
                  <strong>{t.createdAt}:</strong> {formatDateTime(item.created_at)}
                  <br />
                  <strong>{t.status}:</strong> {item.status || "-"}
                </div>
              </div>
            ))
          )}
        </div>
      </section> : null}

      {activeTab === "c" ? <section className="card compact-controls" style={{ marginTop: 14 }}>
        <h2>{t.analysis}</h2>
        <p className="small">LLM status: <strong>{analysis.llm_status || "fallback"}</strong></p>
        {analysis.llm_error ? <p className="small"><strong>LLM error:</strong> {analysis.llm_error}</p> : null}
        <div className="grid two">
          <div>
            <p className="small"><strong>Target roles:</strong> {listToCsv(analysis.target_roles) || "-"}</p>
            <p className="small"><strong>Secondary roles:</strong> {listToCsv(analysis.secondary_roles) || "-"}</p>
            <p className="small"><strong>Seniority:</strong> {analysis.seniority || "unknown"}</p>
            <p className="small"><strong>Industries:</strong> {listToCsv(analysis.industries) || "-"}</p>
          </div>
          <div>
            <p className="small"><strong>Strengths:</strong> {listToCsv(analysis.strengths) || "-"}</p>
            <p className="small"><strong>Skill gaps:</strong> {listToCsv(analysis.skill_gaps) || "-"}</p>
          </div>
        </div>

        <h3 style={{ marginTop: 14 }}>{t.strategy}</h3>
        <p className="small"><strong>Role focus:</strong> {listToCsv(strategy.role_focus) || "-"}</p>
        <div className="toolbar">
          {(strategy.market_roles || []).slice(0, 6).map((item) => (
            <span key={`${item.role}-${item.source}`} className="badge">{item.role} ({item.demand_score})</span>
          ))}
        </div>

        <div style={{ marginTop: 8 }}>
          <p className="small"><strong>{t.recommendedQueries}:</strong></p>
          <div style={{ marginTop: 8, display: "grid", gap: 6 }}>
            {suggestedQueries.length === 0 ? (
              <p className="small">No suggestions yet.</p>
            ) : (
              suggestedQueries.map((item, idx) => (
                <div key={item.id || `${item.text}-${idx}`} className="row" style={{ gridTemplateColumns: "auto 1fr", gap: 8 }}>
                  <input
                    type="checkbox"
                    checked={item.selected !== false}
                    onChange={(e) => toggleSuggestedQuery(idx, e.target.checked)}
                  />
                  <input
                    value={item.text}
                    onChange={(e) => updateSuggestedQuery(idx, e.target.value)}
                    placeholder="AI suggestion"
                  />
                </div>
              ))
            )}
          </div>
        </div>

        <div className="toolbar" style={{ marginTop: 10 }}>
          <button className="ai-reanalyze" onClick={reanalyze} disabled={busy || !cvId}>{t.reanalyze}</button>
          <button className="ai-strategy" onClick={() => run(() => refreshStrategy(cvId))} disabled={busy || !cvId}>{t.loadStrategy}</button>
          <button
            className="secondary"
            type="button"
            disabled={suggestedQueries.length === 0 || suggestedQueries.every((item) => item?.selected === false)}
            onClick={removeSelectedSuggestedQueries}
          >
            {t.strategyDeleteSelected}
          </button>
          <button
            className="secondary"
            type="button"
            disabled={suggestedQueries.length === 0 || suggestedQueries.every((item) => item?.selected === false)}
            onClick={addSelectedSuggestedQueries}
          >
            {t.addToSearch}
          </button>
        </div>

        <h3 style={{ marginTop: 16 }}>{t.insights}</h3>
        <div className="toolbar" style={{ marginTop: 6 }}>
          <button className="ai-strategy" onClick={generateInsight} disabled={busy || !cvId}>{t.generateInsights}</button>
          <button className="secondary" onClick={() => run(() => refreshLatestInsight(cvId))} disabled={busy || !cvId}>{t.refreshInsights}</button>
        </div>
        {!latestInsight ? (
          <p className="small" style={{ marginTop: 8 }}>{t.insightNoData}</p>
        ) : (
          <div style={{ marginTop: 8, display: "grid", gap: 8 }}>
            <p className="small">
              <strong>{t.insightStatus}:</strong> {latestInsight?.insights?.llm_status || "fallback"}
              {latestInsight?.created_at ? ` | ${formatDateTime(latestInsight.created_at)}` : ""}
            </p>
            {latestInsight?.insights?.llm_error ? (
              <p className="small"><strong>LLM error:</strong> {latestInsight.insights.llm_error}</p>
            ) : null}
            <p className="small">
              <strong>Queries +:</strong> {(latestInsight?.insights?.search_improvements?.add_queries || []).slice(0, 8).join(" | ") || "-"}
            </p>
            <p className="small">
              <strong>Queries -:</strong> {(latestInsight?.insights?.search_improvements?.remove_queries || []).slice(0, 8).join(" | ") || "-"}
            </p>
            <p className="small">
              <strong>CV tips:</strong> {(latestInsight?.insights?.cv_recommendations || []).slice(0, 2).map((item) => item.change).join(" | ") || "-"}
            </p>
          </div>
        )}
      </section> : null}

      {activeTab === "a" ? <section className="card" style={{ marginTop: 14 }}>
        <h2>{t.summary}</h2>
        <p className="small">Edita libremente: una línea por elemento en cada campo.</p>
        <div className="grid two">
          <label>
            Highlights
            <textarea
              value={summaryText.highlights}
              onChange={(e) => setSummary((p) => ({ ...p, highlights: linesToList(e.target.value) }))}
            />
          </label>
          <label>
            Skills
            <textarea
              value={summaryText.skills}
              onChange={(e) => setSummary((p) => ({ ...p, skills: linesToList(e.target.value) }))}
            />
          </label>
          <label>
            Experience
            <textarea
              value={summaryText.experience}
              onChange={(e) => setSummary((p) => ({ ...p, experience: linesToList(e.target.value) }))}
            />
          </label>
          <label>
            Education
            <textarea
              value={summaryText.education}
              onChange={(e) => setSummary((p) => ({ ...p, education: linesToList(e.target.value) }))}
            />
          </label>
        </div>
        <label>
          Languages
          <textarea
            value={summaryText.languages}
            onChange={(e) => setSummary((p) => ({ ...p, languages: linesToList(e.target.value) }))}
          />
        </label>
        <div className="toolbar">
          <button onClick={saveSummary} disabled={busy || !cvId}>{t.saveSummary}</button>
        </div>
      </section> : null}

      {activeTab === "d" ? <section className="card compact-controls" style={{ marginTop: 14 }}>
        <h2>{t.search}</h2>
        <div className="row">
          <label>
            Country
            <input value={country} onChange={(e) => setCountry(e.target.value)} placeholder="Chile" />
          </label>
          <label>
            City
            <input value={city} onChange={(e) => setCity(e.target.value)} placeholder="Santiago" />
          </label>
          <label>
            Hours window
            <select value={timeWindow} onChange={(e) => setTimeWindow(e.target.value)}>
              <option value="1">1h</option>
              <option value="3">3h</option>
              <option value="8">8h</option>
              <option value="24">24h</option>
              <option value="72">72h</option>
              <option value="168">1w</option>
              <option value="720">1m</option>
            </select>
          </label>
        </div>
        <div style={{ marginTop: 8 }}>
          <p className="small" style={{ margin: 0, marginBottom: 6 }}>{t.portals}</p>
          <div className="toolbar" style={{ marginTop: 6 }}>
            <button
              type="button"
              className="secondary"
              disabled={availableSources.length === 0}
              onClick={selectAllSources}
            >
              {t.selectAll}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={availableSources.length === 0}
              onClick={deselectAllSources}
            >
              {t.deselectAll}
            </button>
          </div>
          <div style={{ marginTop: 8, display: "grid", gap: 6 }}>
            {availableSources.length === 0 ? (
              <p className="small">No sources available.</p>
            ) : (
              availableSources.map((item) => (
                <label key={item.source_id} className="row" style={{ gridTemplateColumns: "auto 1fr", gap: 8 }}>
                  <input
                    type="checkbox"
                    checked={selectedSources.includes(item.source_id)}
                    disabled={item.enabled === false}
                    onChange={(e) => toggleSearchSource(item.source_id, e.target.checked)}
                  />
                  <span className="small">
                    <strong>{item.label}</strong>
                    {item.description ? ` - ${item.description}` : ""}
                    {item.enabled === false && item.status_note ? ` (${item.status_note})` : ""}
                  </span>
                </label>
              ))
            )}
          </div>
        </div>
        <div>
          <p className="small" style={{ margin: 0, marginBottom: 6 }}>{t.activeQueries}</p>
          <div className="toolbar" style={{ marginTop: 6 }}>
            <input
              value={newQuery}
              onChange={(e) => setNewQuery(e.target.value)}
              placeholder={t.queryPlaceholder}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addManualQuery();
                }
              }}
            />
            <button type="button" className="secondary" onClick={addManualQuery}>{t.addQuery}</button>
          </div>
          <div className="toolbar" style={{ marginTop: 6 }}>
            <button
              type="button"
              className="secondary"
              disabled={queryItems.length === 0}
              onClick={() => setAllQueryItemsEnabled(true)}
            >
              {t.selectAll}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={queryItems.length === 0}
              onClick={() => setAllQueryItemsEnabled(false)}
            >
              {t.deselectAll}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={queryItems.every((item) => item?.enabled === false)}
              onClick={removeSelectedQueryItems}
            >
              {t.deleteSelected}
            </button>
          </div>
          <div style={{ marginTop: 8, display: "grid", gap: 6 }}>
            {queryItems.length === 0 ? (
              <p className="small">No queries yet.</p>
            ) : (
              queryItems.map((item, idx) => (
                <div key={item.id || `${item.text}-${idx}`} className="row" style={{ gridTemplateColumns: "auto 1fr auto", gap: 8 }}>
                  <input
                    type="checkbox"
                    checked={item.enabled !== false}
                    onChange={(e) => toggleQueryItem(idx, e.target.checked)}
                  />
                  <input
                    value={item.text}
                    onChange={(e) => updateQueryItem(idx, e.target.value)}
                    placeholder="Query"
                  />
                  <button type="button" className="secondary" onClick={() => removeQueryItem(idx)}>{t.remove}</button>
                </div>
              ))
            )}
          </div>
          <p className="small">{t.enabledQueries}: {enabledQueryCount}</p>
        </div>
        <div className="toolbar">
          <button onClick={createSearch} disabled={busy || !cvId}>{t.runSearch}</button>
          <button className="secondary" onClick={rerunSearch} disabled={busy || !searchId}>Run Again</button>
          <span className="small">Search ID: {searchId || "-"}</span>
        </div>
      </section> : null}

      {activeTab === "d" ? <section className="card" style={{ marginTop: 14 }}>
        <h2>{t.results}</h2>
        <div className="row">
          <label>
            Sort
            <select
              value={sortBy}
              onChange={(e) => {
                setSortBy(e.target.value);
                setResultsPage(1);
              }}
            >
              <option value="newest">Newest</option>
              <option value="best_fit">Best Fit</option>
            </select>
          </label>
          <label>
            {t.source}
            <select
              value={sourceFilter}
              onChange={(e) => {
                setSourceFilter(e.target.value);
                setResultsPage(1);
              }}
            >
              <option value="">All</option>
              {sourceOptions.map((key) => (
                <option key={key} value={key}>{key} ({facets.sources[key]})</option>
              ))}
            </select>
          </label>
          <label>
            Category
            <select
              value={categoryFilter}
              onChange={(e) => {
                setCategoryFilter(e.target.value);
                setResultsPage(1);
              }}
            >
              <option value="">All</option>
              {categoryOptions.map((key) => (
                <option key={key} value={key}>{key} ({facets.categories[key]})</option>
              ))}
            </select>
          </label>
          <label>
            Subcategory
            <select
              value={subcategoryFilter}
              onChange={(e) => {
                setSubcategoryFilter(e.target.value);
                setResultsPage(1);
              }}
            >
              <option value="">All</option>
              {subcategoryOptions.map((key) => (
                <option key={key} value={key}>{key} ({facets.subcategories[key]})</option>
              ))}
            </select>
          </label>
          <label>
            Max posted hours
            <select
              value={maxPostedHours}
              onChange={(e) => {
                setMaxPostedHours(e.target.value);
                setResultsPage(1);
              }}
            >
              <option value="">Any</option>
              <option value="1">1h</option>
              <option value="3">3h</option>
              <option value="8">8h</option>
              <option value="24">24h</option>
              <option value="72">72h</option>
              <option value="168">1w</option>
              <option value="720">1m</option>
            </select>
          </label>
          <label>
            Location contains
            <input
              value={locationContains}
              onChange={(e) => {
                setLocationContains(e.target.value);
                setResultsPage(1);
              }}
              placeholder="Santiago"
            />
          </label>
          <label>
            {t.pageSize}
            <select
              value={resultsPageSize}
              onChange={(e) => {
                setResultsPageSize(e.target.value);
                setResultsPage(1);
              }}
            >
              <option value="25">25</option>
              <option value="50">50</option>
              <option value="100">100</option>
            </select>
          </label>
        </div>
        <div className="toolbar" style={{ marginTop: 8 }}>
          <button
            type="button"
            className="secondary"
            disabled={busy || !searchId || results.length === 0}
            onClick={() => setAllResultsChecked(true)}
          >
            {t.selectAll}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={busy || !searchId || results.length === 0}
            onClick={() => setAllResultsChecked(false)}
          >
            {t.deselectAll}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={busy || !searchId || resultsMeta.total === 0}
            onClick={clearSearchResults}
          >
            {t.clearResults}
          </button>
          <span className="small">
            {t.total}: {resultsMeta.total}
          </span>
          <span className="small">
            {t.page} {resultsMeta.page} {t.of} {resultsMeta.total_pages || 0}
          </span>
          <button
            type="button"
            className="secondary"
            disabled={busy || !searchId || !resultsMeta.has_prev}
            onClick={() => setResultsPage((p) => Math.max(1, p - 1))}
          >
            {t.prev}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={busy || !searchId || !resultsMeta.has_next}
            onClick={() => setResultsPage((p) => p + 1)}
          >
            {t.next}
          </button>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Check</th>
                <th>Title</th>
                <th>{t.source}</th>
                <th>Category</th>
                <th>Subcategory</th>
                <th>Description</th>
                <th>Mode</th>
                <th>Easy Apply</th>
                <th>Applicants</th>
                <th>% Match</th>
                <th>LLM Fit</th>
                <th>Final Score</th>
                <th>Reasons</th>
                <th>Apply</th>
              </tr>
            </thead>
            <tbody>
              {results.length === 0 ? (
                <tr>
                  <td colSpan={14} className="small">No results yet.</td>
                </tr>
              ) : (
                results.map((row) => (
                  <tr key={row.result_id} className={row.is_new ? "new-row" : ""}>
                    <td>
                      <input
                        type="checkbox"
                        checked={row.checked}
                        onChange={(e) => setChecked(row, e.target.checked)}
                      />
                    </td>
                    <td>
                      <strong>{row.title}</strong>
                      <div className="small">{row.company || "-"} | {row.location || "-"}</div>
                      <div className="small">posted: {row.posted_age_hours == null ? "-" : `${row.posted_age_hours}h`}</div>
                      {row.is_new ? <span className="badge">NEW</span> : null}
                    </td>
                    <td>{row.source || "-"}</td>
                    <td>{row.job_category || "-"}</td>
                    <td>{row.job_subcategory || "-"}</td>
                    <td className="small">{row.description?.slice(0, 220) || "-"}</td>
                    <td>{row.modality || "-"}</td>
                    <td>{row.easy_apply ? "Yes" : "No"}</td>
                    <td>{row.applicant_count ?? 0}</td>
                    <td>{row.match_percent?.toFixed?.(2) ?? row.match_percent}</td>
                    <td>{row.llm_fit_score?.toFixed?.(2) ?? row.llm_fit_score}</td>
                    <td><strong>{row.final_score?.toFixed?.(2) ?? row.final_score}</strong></td>
                    <td className="small">{(row.fit_reasons || []).slice(0, 2).join(" | ") || "-"}</td>
                    <td>
                      <a
                        className="job-link"
                        href={row.job_url}
                        target="_blank"
                        rel="noreferrer"
                        onClick={() =>
                          logInteraction({
                            cv_id: cvId,
                            session_id: sessionId || null,
                            search_id: searchId || null,
                            result_id: row.result_id,
                            job_id: row.job_id,
                            event_type: "open",
                            meta: {
                              title: row.title,
                              source: row.source,
                              url: row.job_url,
                            },
                          })
                        }
                      >
                        Open
                      </a>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section> : null}
    </main>
  );
}
