"use client";

import { useId, useMemo, useState } from "react";

import { ShotTarget } from "@/components/shot-target";
import type { ActivityPhase, ActivityShot } from "@/lib/types";

interface PhaseCardProps {
  contextLabel?: string;
  phase: ActivityPhase;
}

export function PhaseCard({ contextLabel, phase }: PhaseCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [hoveredShotKey, setHoveredShotKey] = useState<string | null>(null);
  const [selectedShotKeys, setSelectedShotKeys] = useState<Set<string>>(
    () => new Set(),
  );
  const series = useMemo(() => chunkShots(phase.shots, 10), [phase.shots]);
  const isMatch = phase.kind === "match";
  const title = isMatch
    ? `Match relay ${phase.ordinal}`
    : `Sighter block ${phase.ordinal}`;
  const contentId = useId();

  function toggleShot(shotKey: string) {
    setSelectedShotKeys((current) => {
      const next = new Set(current);
      if (next.has(shotKey)) {
        next.delete(shotKey);
      } else {
        next.add(shotKey);
      }
      return next;
    });
  }

  function toggleSeries(shots: ActivityShot[]) {
    setSelectedShotKeys((current) => {
      const next = new Set(current);
      const allSelected = shots.every((shot) => next.has(shot.shotKey));
      for (const shot of shots) {
        if (allSelected) {
          next.delete(shot.shotKey);
        } else {
          next.add(shot.shotKey);
        }
      }
      return next;
    });
  }

  return (
    <section className={`phase-card phase-${phase.kind}`}>
      <header className="phase-header">
        <button
          aria-controls={contentId}
          aria-expanded={expanded}
          className="phase-toggle"
          onClick={() => setExpanded((current) => !current)}
          type="button"
        >
          <div className="phase-title">
            <span className={`phase-badge phase-badge-${phase.kind}`}>
              {isMatch ? "Match" : "Sighters"}
            </span>
            <div>
              <h4>{title}</h4>
              {contextLabel ? <small>{contextLabel}</small> : null}
            </div>
          </div>
          <div className="phase-stats">
            <span>
              <strong>{phase.stats.shotCount}</strong>{" "}
              {phase.stats.shotCount === 1 ? "shot" : "shots"}
            </span>
            <span>
              <strong>{phase.stats.scoreTotal.toFixed(1)}</strong> total
            </span>
            <span>
              <strong>
                {phase.stats.averageScore === null
                  ? "—"
                  : phase.stats.averageScore.toFixed(2)}
              </strong>{" "}
              avg
            </span>
            <span title="Target type inferred from the SIUS score encoding">
              {phase.targetKind === "air-pistol" ? "Air pistol" : "Air rifle"}
            </span>
            <span className="expand-label">
              {expanded ? "Hide shots" : "Show shots"}
              <span aria-hidden="true" className="expand-chevron">
                {expanded ? "−" : "+"}
              </span>
            </span>
          </div>
        </button>
      </header>

      {expanded ? <div className="phase-content" id={contentId}>
        <ShotTarget
          hoveredShotKey={hoveredShotKey}
          selectedShotKeys={selectedShotKeys}
          shots={phase.shots}
          targetKind={phase.targetKind}
        />

        <div className="shot-series" aria-label={`${title} shot list`}>
          {series.map((shots, seriesIndex) => {
            const total = shots.reduce(
              (sum, shot) => sum + shot.scoreTenths,
              0,
            );
            const label = isMatch
              ? `Series ${seriesIndex + 1}`
              : series.length === 1
                ? "Sighters"
                : `Sighters ${seriesIndex * 10 + 1}–${seriesIndex * 10 + shots.length}`;
            return (
              <div className="series-block" key={shots[0]?.shotKey ?? seriesIndex}>
                <button
                  className="series-heading"
                  onClick={() => toggleSeries(shots)}
                  type="button"
                >
                  <span>{label}</span>
                  <strong>{(total / 10).toFixed(1)}</strong>
                </button>
                <div className="shot-grid">
                  {shots.map((shot) => {
                    const selected = selectedShotKeys.has(shot.shotKey);
                    return (
                      <button
                        aria-pressed={selected}
                        className={`shot-chip ${selected ? "shot-chip-selected" : ""}`}
                        key={shot.shotKey}
                        onClick={() => toggleShot(shot.shotKey)}
                        onFocus={() => setHoveredShotKey(shot.shotKey)}
                        onBlur={() => setHoveredShotKey(null)}
                        onMouseEnter={() => setHoveredShotKey(shot.shotKey)}
                        onMouseLeave={() => setHoveredShotKey(null)}
                        title={`Shot ${shot.shotNumber}: ${shot.score.toFixed(1)} at ${shot.deviceTime}`}
                        type="button"
                      >
                        <small>{shot.shotNumber}</small>
                        <strong>{shot.score.toFixed(1)}</strong>
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}

          {selectedShotKeys.size > 0 ? (
            <button
              className="clear-button"
              onClick={() => setSelectedShotKeys(new Set())}
              type="button"
            >
              Clear {selectedShotKeys.size} selected
            </button>
          ) : (
            <p className="interaction-hint">
              Hover a score to locate it. Select shots or a series to compare.
            </p>
          )}
        </div>
      </div> : null}
    </section>
  );
}

function chunkShots(shots: ActivityShot[], size: number): ActivityShot[][] {
  const chunks: ActivityShot[][] = [];
  for (let index = 0; index < shots.length; index += size) {
    chunks.push(shots.slice(index, index + size));
  }
  return chunks;
}
