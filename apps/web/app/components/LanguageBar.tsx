"use client";

export function LanguageBar({ languages }: { languages: Record<string, number> }) {
  const LANGUAGE_COLORS: Record<string, string> = {
    TypeScript: "#3178c6",
    JavaScript: "#f1e05a",
    Python: "#3572A5",
    Rust: "#dea584",
    Go: "#00ADD8",
    Java: "#b07219",
    C: "#555555",
    "C++": "#f34b7d",
    "C#": "#178600",
    Ruby: "#701516",
    Swift: "#F05138",
    Kotlin: "#A97BFF",
    Dart: "#00B4AB",
    PHP: "#4F5D95",
    Shell: "#89e051",
    HTML: "#e34c26",
    CSS: "#563d7c",
    Vue: "#41b883",
    Svelte: "#ff3e00",
  };

  const total = Object.values(languages).reduce((acc, count) => acc + count, 0);
  const sortedLanguages = Object.entries(languages).sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0));

  return (
    <div className="chartPanel">
      <div className="sectionTitle">
        <span>Languages</span>
        <small>Primary repositories</small>
      </div>
      <div className="languageTrack">
        {sortedLanguages.map(([lang, count]) => (
          <span 
            key={lang} 
            style={{ 
              width: `${(count / total) * 100}%`, 
              backgroundColor: LANGUAGE_COLORS[lang] || "var(--muted)" 
            }} 
            title={`${lang}: ${count} repos`}
          />
        ))}
      </div>
      <div className="languageLegend">
        {sortedLanguages.map(([lang, count]) => {
          const pct = Math.round((count / total) * 100);
          return (
            <span key={lang}>
              <i className="languageDot" style={{ backgroundColor: LANGUAGE_COLORS[lang] || "var(--muted)" }} />
              {lang} {pct}%
            </span>
          );
        })}
      </div>
    </div>
  );
}
