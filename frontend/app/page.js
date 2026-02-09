"use client";

import { useEffect, useMemo, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api";

const I18N = {
  es: {
    title: "Buscador LinkedIn desde CV",
    subtitle: "Sube CV, revisa análisis IA y prioriza ofertas por mejor encaje.",
    upload: "Subir CV",
    summary: "Resumen del CV",
    analysis: "Análisis IA del perfil",
    strategy: "Estrategia de búsqueda",
    loadStrategy: "Actualizar estrategia",
    search: "Búsqueda",
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
    page: "Página",
    of: "de",
    total: "Total",
    pageSize: "Tamaño de página",
    prev: "Anterior",
    next: "Siguiente",
  },
  en: {
    title: "LinkedIn Job Finder from CV",
    subtitle: "Upload CV, review AI analysis, and prioritize jobs by best fit.",
    upload: "Upload CV",
    summary: "CV Summary",
    analysis: "AI Profile Analysis",
    strategy: "Search strategy",
    loadStrategy: "Refresh strategy",
    search: "Search",
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
    page: "Page",
    of: "of",
    total: "Total",
    pageSize: "Page size",
    prev: "Prev",
    next: "Next",
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

function mergeQueryItems(existing, incoming, options = {}) {
  const enabled = options.enabled ?? true;
  const source = options.source || "manual";
  const byKey = new Map();

  for (const item of existing || []) {
    const text = normalizeQuery(item?.text || item);
    if (!text) continue;
    byKey.set(text.toLowerCase(), {
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
    byKey.set(key, { text, enabled, source });
  }

  return Array.from(byKey.values());
}

function activeQueryList(items) {
  const enabledItems = (items || [])
    .filter((item) => item?.enabled !== false)
    .map((item) => item?.text || "");
  return uniqueList(enabledItems);
}

export default function Home() {
  const [lang, setLang] = useState("es");
  const t = I18N[lang];

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const [file, setFile] = useState(null);
  const [cvId, setCvId] = useState("");

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
  const [queryItems, setQueryItems] = useState([]);
  const [newQuery, setNewQuery] = useState("");

  const [sortBy, setSortBy] = useState("newest");
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
    categories: {},
    subcategories: {},
    modalities: {},
    locations: {},
    posted_buckets: {},
  });
  const [scheduler, setScheduler] = useState({ is_running: false, interval_minutes: 30, last_tick_at: null });

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

  const refreshStrategy = async (targetCvId = cvId) => {
    if (!targetCvId) return;
    const out = await api(`/cv/${targetCvId}/strategy`);
    setStrategy(out);
    setQueryItems((prev) =>
      mergeQueryItems(prev, out.recommended_queries || [], { enabled: true, source: "strategy" }),
    );
  };

  const buildResultsPath = (targetSearchId) => {
    const params = new URLSearchParams();
    params.set("sort_by", sortBy);
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

  useEffect(() => {
    refreshScheduler().catch(() => null);
  }, []);

  useEffect(() => {
    if (!searchId) return;
    refreshResults(searchId).catch(() => null);
  }, [searchId, sortBy, categoryFilter, subcategoryFilter, maxPostedHours, locationContains, resultsPage, resultsPageSize]);

  useEffect(() => {
    if (!searchId) return;
    const id = setInterval(() => {
      refreshResults(searchId).catch(() => null);
      refreshScheduler().catch(() => null);
      refreshFacets(searchId).catch(() => null);
    }, 30000);
    return () => clearInterval(id);
  }, [searchId, sortBy, categoryFilter, subcategoryFilter, maxPostedHours, locationContains, resultsPage, resultsPageSize]);

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
      setCvId(out.cv_id);
      setSummary(out.summary);
      setAnalysis(out.analysis || analysis);
      setQueryItems((prev) =>
        mergeQueryItems(prev, out.analysis?.recommended_queries || [], { enabled: true, source: "analysis" }),
      );

      await refreshStrategy(out.cv_id);
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
      setQueryItems((prev) =>
        mergeQueryItems(prev, out.analysis?.recommended_queries || [], { enabled: true, source: "analysis" }),
      );
      await refreshStrategy(cvId);
    });

  const reanalyze = () =>
    run(async () => {
      if (!cvId) throw new Error("Upload CV first");
      const out = await api(`/cv/${cvId}/analyze`, { method: "POST" });
      setSummary(out.summary);
      setAnalysis(out.analysis || analysis);
      setQueryItems((prev) =>
        mergeQueryItems(prev, out.analysis?.recommended_queries || [], { enabled: true, source: "analysis" }),
      );
      await refreshStrategy(cvId);
    });

  const createSearch = () =>
    run(async () => {
      if (!cvId) throw new Error("Upload and confirm CV first");
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
        }),
      });
      await api(`/searches/${searchId}/run`, { method: "POST" });
      setResultsPage(1);
      await refreshResults(searchId);
      await refreshFacets(searchId);
    });

  const setChecked = (resultId, checked) =>
    run(async () => {
      await api(`/searches/results/${resultId}/check`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ checked }),
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
      await refreshResults(searchId);
    });

  const startScheduler = () =>
    run(async () => {
      const out = await api("/scheduler/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ interval_minutes: 30 }),
      });
      setScheduler(out);
    });

  const stopScheduler = () =>
    run(async () => {
      const out = await api("/scheduler/stop", { method: "POST" });
      setScheduler(out);
    });

  const addRecommendedQuery = (query) => {
    setQueryItems((prev) => {
      const key = normalizeQuery(query).toLowerCase();
      const next = [...prev];
      const idx = next.findIndex((item) => normalizeQuery(item.text).toLowerCase() === key);
      if (idx >= 0) {
        next[idx] = { ...next[idx], enabled: true };
        return next;
      }
      return mergeQueryItems(next, [query], { enabled: true, source: "recommended" });
    });
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

  const enabledQueryCount = activeQueryList(queryItems).length;

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

      <div className="grid two">
        <section className="card">
          <h2>{t.upload}</h2>
          <label>
            CV (.pdf / .docx)
            <input type="file" accept=".pdf,.docx" onChange={(e) => setFile(e.target.files?.[0] || null)} />
          </label>
          <div className="toolbar">
            <button onClick={uploadCv} disabled={busy || !file}>Upload</button>
            <span className="small">CV ID: {cvId || "-"}</span>
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
      </div>

      <section className="card" style={{ marginTop: 14 }}>
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
          <div className="toolbar">
            {uniqueList([...(analysis.recommended_queries || []), ...(strategy.recommended_queries || [])]).map((q) => (
              <button key={q} className="secondary" type="button" onClick={() => addRecommendedQuery(q)}>
                + {q}
              </button>
            ))}
          </div>
        </div>

        <div className="toolbar" style={{ marginTop: 10 }}>
          <button className="secondary" onClick={reanalyze} disabled={busy || !cvId}>{t.reanalyze}</button>
          <button className="secondary" onClick={() => run(() => refreshStrategy(cvId))} disabled={busy || !cvId}>{t.loadStrategy}</button>
        </div>
      </section>

      <section className="card" style={{ marginTop: 14 }}>
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
      </section>

      <section className="card" style={{ marginTop: 14 }}>
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
        <label>
          {t.activeQueries}
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
          </div>
          <div style={{ marginTop: 8, display: "grid", gap: 6 }}>
            {queryItems.length === 0 ? (
              <p className="small">No queries yet.</p>
            ) : (
              queryItems.map((item, idx) => (
                <div key={`${item.text}-${idx}`} className="row" style={{ gridTemplateColumns: "auto 1fr auto", gap: 8 }}>
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
        </label>
        <div className="toolbar">
          <button onClick={createSearch} disabled={busy || !cvId}>{t.runSearch}</button>
          <button className="secondary" onClick={rerunSearch} disabled={busy || !searchId}>Run Again</button>
          <span className="small">Search ID: {searchId || "-"}</span>
        </div>
      </section>

      <section className="card" style={{ marginTop: 14 }}>
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
                  <td colSpan={13} className="small">No results yet.</td>
                </tr>
              ) : (
                results.map((row) => (
                  <tr key={row.result_id} className={row.is_new ? "new-row" : ""}>
                    <td>
                      <input
                        type="checkbox"
                        checked={row.checked}
                        onChange={(e) => setChecked(row.result_id, e.target.checked)}
                      />
                    </td>
                    <td>
                      <strong>{row.title}</strong>
                      <div className="small">{row.company || "-"} | {row.location || "-"}</div>
                      <div className="small">posted: {row.posted_age_hours == null ? "-" : `${row.posted_age_hours}h`}</div>
                      {row.is_new ? <span className="badge">NEW</span> : null}
                    </td>
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
                      <a className="job-link" href={row.job_url} target="_blank" rel="noreferrer">
                        Open
                      </a>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
