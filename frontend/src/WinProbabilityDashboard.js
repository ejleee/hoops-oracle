import React, { useEffect, useState } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ReferenceLine, ResponsiveContainer,
} from 'recharts';
import useGameSocket from './useGameSocket';
import { getMatchupColors } from './teamColors';

const GAME_SECONDS = 48 * 60;

const theme = {
  bg: '#0a0e1a',
  panel: '#111827',
  border: '#1f2937',
  text: '#e5e7eb',
  muted: '#6b7280',
  home: '#38bdf8',
  away: '#f87171',
  green: '#34d399',
  accent: '#818cf8',
};

function parseClock(clockStr, period) {
  if (!clockStr) return { display: '–', secondsLeft: 0 };
  const m = clockStr.match(/PT(\d+)M([\d.]+)S/);
  if (!m) return { display: clockStr, secondsLeft: 0 };
  const mins = parseInt(m[1]);
  const secs = Math.floor(parseFloat(m[2]));
  const periodRemaining = mins * 60 + secs;
  const fullQtrsLeft = Math.max(0, 4 - period);
  const totalLeft = fullQtrsLeft * 720 + periodRemaining;
  return {
    display: `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`,
    secondsLeft: totalLeft,
  };
}

function Panel({ children, style }) {
  return (
    <div style={{
      background: theme.panel,
      border: `1px solid ${theme.border}`,
      borderRadius: 10,
      padding: 16,
      ...style,
    }}>
      {children}
    </div>
  );
}

function Label({ children }) {
  return (
    <div style={{ fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase', color: theme.muted, marginBottom: 4 }}>
      {children}
    </div>
  );
}

function ProbBar({ homeProb, homeTricode, awayTricode, homeColor, awayColor }) {
  const awayProb = 1 - homeProb;
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: theme.muted, marginBottom: 6 }}>
        <span style={{ color: awayColor }}>{awayTricode} {Math.round(awayProb * 100)}%</span>
        <span style={{ color: homeColor }}>{homeTricode} {Math.round(homeProb * 100)}%</span>
      </div>
      <div style={{ display: 'flex', height: 6, borderRadius: 3, overflow: 'hidden', background: theme.border }}>
        <div style={{ width: `${awayProb * 100}%`, background: awayColor, transition: 'width 0.6s ease' }} />
        <div style={{ width: `${homeProb * 100}%`, background: homeColor, transition: 'width 0.6s ease' }} />
      </div>
    </div>
  );
}

function PlayFeed({ plays, homeProbHistory, homeTricode, homeColor, awayColor }) {
  const enriched = [...plays].reverse();
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {enriched.map((play, i) => {
        const probEntry = homeProbHistory[homeProbHistory.length - 1 - i];
        const delta = probEntry?.delta;
        const m = play.clock?.match(/PT(\d+)M([\d.]+)S/);
        const clockDisplay = m
          ? `${m[1]}:${String(Math.floor(parseFloat(m[2]))).padStart(2, '0')}`
          : play.clock;
        return (
          <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 12 }}>
            <span style={{ color: theme.muted, minWidth: 36, flexShrink: 0 }}>{clockDisplay}</span>
            <span style={{ color: theme.text, flex: 1 }}>{play.description}</span>
            {delta !== undefined && (
              <span style={{
                color: delta > 0 ? homeColor : awayColor,
                fontWeight: 700,
                minWidth: 40,
                textAlign: 'right',
              }}>
                {delta > 0 ? '+' : ''}{Math.round(delta * 100)}%
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  const elapsed = GAME_SECONDS - (payload[0]?.payload?.secondsLeft ?? 0);
  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  return (
    <div style={{ background: theme.panel, border: `1px solid ${theme.border}`, padding: '6px 10px', borderRadius: 6, fontSize: 12 }}>
      <div style={{ color: theme.muted }}>{mins}:{String(secs).padStart(2, '0')} elapsed</div>
      <div style={{ color: theme.home, fontWeight: 700 }}>{Math.round(payload[0].value * 100)}%</div>
    </div>
  );
};

export default function WinProbabilityDashboard() {
  const { gameUpdates, gamesList, connected } = useGameSocket();
  const [selectedGameId, setSelectedGameId] = useState(null);
  const [history, setHistory] = useState(() => {
    try { return JSON.parse(localStorage.getItem('hoops_history') || '{}'); }
    catch { return {}; }
  });
  const [probHistory, setProbHistory] = useState(() => {
    try { return JSON.parse(localStorage.getItem('hoops_prob_history') || '{}'); }
    catch { return {}; }
  });

  // Auto-select first game when list arrives and nothing is selected yet
  useEffect(() => {
    if (gamesList.length > 0 && !selectedGameId) {
      setSelectedGameId(gamesList[0].game_id);
    }
    // If selected game ended/disappeared, fall back to first available
    if (selectedGameId && gamesList.length > 0 && !gamesList.find(g => g.game_id === selectedGameId)) {
      setSelectedGameId(gamesList[0].game_id);
    }
  }, [gamesList, selectedGameId]);

  // Fall back to first available update if nothing is explicitly selected (e.g. replay mode)
  const activeGameId = selectedGameId ?? Object.keys(gameUpdates)[0] ?? null;
  const gameData = activeGameId ? gameUpdates[activeGameId] : null;

  // Persist history to localStorage whenever it changes
  useEffect(() => {
    localStorage.setItem('hoops_history', JSON.stringify(history));
  }, [history]);

  useEffect(() => {
    localStorage.setItem('hoops_prob_history', JSON.stringify(probHistory));
  }, [probHistory]);

  // Accumulate chart + prob history per game
  useEffect(() => {
    if (!gameData) return;
    const gid = gameData.game_id;
    const prob = gameData.home_win_prob ?? 0.5;
    const { secondsLeft } = parseClock(gameData.clock, gameData.quarter ?? 1);
    const elapsed = GAME_SECONDS - secondsLeft;

    setHistory(prev => {
      const pts = prev[gid] ?? [];
      const last = pts[pts.length - 1];
      if (last && last.elapsed === elapsed) return prev;
      return { ...prev, [gid]: [...pts, { elapsed, prob, secondsLeft }] };
    });

    setProbHistory(prev => {
      const pts = prev[gid] ?? [];
      const lastProb = pts[pts.length - 1]?.prob ?? 0.5;
      return { ...prev, [gid]: [...pts, { prob, delta: prob - lastProb }] };
    });
  }, [gameData]);

  const noGame = connected && gamesList.length === 0 && !gameData;

  const homeProb = gameData?.home_win_prob ?? 0.5;
  const homeTricode = gameData?.home_team ?? 'HOME';
  const awayTricode = gameData?.away_team ?? 'AWAY';
  const { awayColor, homeColor } = getMatchupColors(awayTricode, homeTricode);
  const homeName = gameData ? `${gameData.home_team_city} ${gameData.home_team_name}` : 'Home Team';
  const awayName = gameData ? `${gameData.away_team_city} ${gameData.away_team_name}` : 'Away Team';
  const homeScore = gameData?.home_score ?? 0;
  const awayScore = gameData?.away_score ?? 0;
  const quarter = gameData?.quarter ?? 1;
  const { display: clockDisplay } = parseClock(gameData?.clock, quarter);
  const recentPlays = gameData?.recent_plays ?? [];
  const chartHistory = (selectedGameId ? history[selectedGameId] : null) ?? [];
  const chartProbHistory = (selectedGameId ? probHistory[selectedGameId] : null) ?? [];

  const s = { color: theme.text, fontFamily: "'Inter', 'system-ui', sans-serif", background: theme.bg, minHeight: '100vh', padding: 20 };

  return (
    <div style={s}>

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {/* Basketball SVG icon */}
          <svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="14" cy="14" r="13" stroke="#C8102E" strokeWidth="2" fill="none"/>
            <path d="M14 1 Q14 14 14 27" stroke="#C8102E" strokeWidth="1.5"/>
            <path d="M1 14 Q14 14 27 14" stroke="#C8102E" strokeWidth="1.5"/>
            <path d="M3.5 5.5 Q14 14 24.5 22.5" stroke="#C8102E" strokeWidth="1.5"/>
            <path d="M24.5 5.5 Q14 14 3.5 22.5" stroke="#C8102E" strokeWidth="1.5"/>
          </svg>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 0 }}>
            <span style={{ fontWeight: 800, fontSize: 18, letterSpacing: '0.15em', color: '#C8102E' }}>HOOPS</span>
            <span style={{ fontWeight: 800, fontSize: 18, letterSpacing: '0.15em', color: '#1D428A' }}> ORACLE</span>
          </div>
          <span style={{ fontSize: 13, color: theme.muted, letterSpacing: '0.06em' }}>· LIVE WIN PROBABILITY</span>
          {gamesList.length > 0 && (
            <span style={{ fontSize: 11, color: theme.muted, letterSpacing: '0.08em' }}>
              · {gamesList.length} LIVE {gamesList.length === 1 ? 'GAME' : 'GAMES'}
            </span>
          )}
        </div>

        {/* Game selector — only shown when 2+ games are live */}
        {gamesList.length > 1 && (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {gamesList.map(g => {
              const active = g.game_id === selectedGameId;
              const { display: gClock } = parseClock(g.clock, g.quarter);
              return (
                <button
                  key={g.game_id}
                  onClick={() => setSelectedGameId(g.game_id)}
                  style={{
                    padding: '6px 12px',
                    borderRadius: 8,
                    border: `1px solid ${active ? theme.accent : theme.border}`,
                    background: active ? theme.accent + '22' : theme.panel,
                    color: active ? theme.accent : theme.muted,
                    fontSize: 12,
                    fontWeight: active ? 700 : 400,
                    cursor: 'pointer',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {g.away_team} @ {g.home_team}
                  <span style={{ marginLeft: 8, color: theme.muted, fontSize: 11 }}>
                    Q{g.quarter} {gClock}
                  </span>
                </button>
              );
            })}
          </div>
        )}

        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
          <span style={{ fontSize: 20, filter: connected ? 'none' : 'grayscale(100%) opacity(0.4)' }}>🏀</span>
          <span style={{ color: connected ? theme.green : theme.muted }}>
            {connected ? 'LIVE' : 'NO GAME TO DISPLAY'}
          </span>
        </div>
      </div>

      {/* No game banner */}
      {noGame && (
        <Panel style={{ textAlign: 'center', padding: 32, marginBottom: 16 }}>
          <div style={{ fontSize: 16, color: theme.muted }}>No live NBA games right now.</div>
          <div style={{ fontSize: 12, color: theme.muted, marginTop: 8 }}>
            The tracker will update automatically when a game starts.
          </div>
        </Panel>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 16, alignItems: 'start' }}>

        {/* LEFT column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

          {/* Scoreboard */}
          <Panel>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', alignItems: 'center', gap: 16 }}>

              {/* Away */}
              <div>
                <Label>Away</Label>
                <div style={{ fontSize: 22, fontWeight: 800 }}>{awayTricode}</div>
                <div style={{ fontSize: 12, color: theme.muted }}>{awayName}</div>
                <div style={{ fontSize: 56, fontWeight: 900, color: awayColor, lineHeight: 1.1, marginTop: 4 }}>
                  {awayScore}
                </div>
              </div>

              {/* Clock */}
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 11, color: theme.muted, marginBottom: 2 }}>
                  Q{quarter}
                </div>
                <div style={{ fontSize: 28, fontWeight: 700, letterSpacing: '0.05em' }}>{clockDisplay}</div>
                <div style={{ marginTop: 6, fontSize: 11, color: theme.muted }}>
                  {gameData?.home_possession === 1 ? `${homeTricode} ball` : gameData ? `${awayTricode} ball` : '–'}
                </div>
              </div>

              {/* Home */}
              <div style={{ textAlign: 'right' }}>
                <Label>Home</Label>
                <div style={{ fontSize: 22, fontWeight: 800 }}>{homeTricode}</div>
                <div style={{ fontSize: 12, color: theme.muted }}>{homeName}</div>
                <div style={{ fontSize: 56, fontWeight: 900, color: homeColor, lineHeight: 1.1, marginTop: 4 }}>
                  {homeScore}
                </div>
              </div>
            </div>

            {/* Probability headline */}
            <div style={{ borderTop: `1px solid ${theme.border}`, marginTop: 16, paddingTop: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
              <div>
                <Label>Win probability · neural network output</Label>
                <div style={{ fontSize: 52, fontWeight: 900, color: awayColor, lineHeight: 1 }}>
                  {Math.round((1 - homeProb) * 100)}%
                </div>
                <div style={{ fontSize: 13, color: theme.muted, marginTop: 4 }}>{awayName}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 52, fontWeight: 900, color: homeColor, lineHeight: 1 }}>
                  {Math.round(homeProb * 100)}%
                </div>
                <div style={{ fontSize: 13, color: theme.muted, marginTop: 4 }}>{homeName}</div>
              </div>
            </div>

            <ProbBar homeProb={homeProb} homeTricode={homeTricode} awayTricode={awayTricode} homeColor={homeColor} awayColor={awayColor} />
          </Panel>

          {/* Chart */}
          <Panel>
            <Label>Win probability over time · {homeTricode}</Label>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={chartHistory} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={theme.border} />
                <XAxis
                  dataKey="elapsed"
                  tickFormatter={v => `${Math.floor(v / 60)}'`}
                  tick={{ fontSize: 10, fill: theme.muted }}
                  domain={[0, GAME_SECONDS]}
                />
                <YAxis
                  domain={[0, 1]}
                  tickFormatter={v => `${Math.round(v * 100)}%`}
                  tick={{ fontSize: 10, fill: theme.muted }}
                />
                <Tooltip content={<CustomTooltip />} />
                <ReferenceLine y={0.5} stroke={theme.border} strokeDasharray="4 2" />
                <Line
                  type="monotone"
                  dataKey="prob"
                  stroke={homeColor}
                  strokeWidth={2}
                  dot={chartHistory.length < 50 ? { r: 3, fill: homeColor } : false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </Panel>

          {/* Play feed */}
          <Panel>
            <Label>Play feed</Label>
            {recentPlays.length === 0
              ? <div style={{ color: theme.muted, fontSize: 12, marginTop: 8 }}>Waiting for plays…</div>
              : <PlayFeed plays={recentPlays} homeProbHistory={chartProbHistory} homeTricode={homeTricode} homeColor={homeColor} awayColor={awayColor} />
            }
          </Panel>
        </div>

        {/* RIGHT column — model inputs */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Panel>
            <Label>Model inputs · current state</Label>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 12 }}>
              {[
                ['Score differential', gameData ? `${gameData.score_differential > 0 ? '+' : ''}${gameData.score_differential} ${homeTricode}` : '–', gameData?.score_differential > 0 ? homeColor : awayColor],
                ['Time remaining', gameData ? `${Math.floor((gameData.seconds_remaining ?? 0) / 60)}m ${Math.round((gameData.seconds_remaining ?? 0) % 60)}s` : '–', theme.text],
                ['Possession', gameData ? (gameData.home_possession ? homeTricode : awayTricode) : '–', theme.text],
                [`${homeTricode} team fouls`, gameData?.home_fouls ?? '–', gameData?.home_fouls >= 5 ? awayColor : theme.text, gameData?.home_fouls >= 5 ? ' (bonus)' : ''],
                [`${awayTricode} team fouls`, gameData?.away_fouls ?? '–', gameData?.away_fouls >= 5 ? awayColor : theme.text, gameData?.away_fouls >= 5 ? ' (bonus)' : ''],
                [`${homeTricode} win rate`, gameData ? `${Math.round((gameData.home_win_rate ?? 0.5) * 100)}%` : '–', theme.text],
                [`${awayTricode} win rate`, gameData ? `${Math.round((gameData.away_win_rate ?? 0.5) * 100)}%` : '–', theme.text],
              ].map(([label, value, color, suffix = '']) => (
                <div key={label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 13 }}>
                  <span style={{ color: theme.muted }}>{label}</span>
                  <span style={{ color, fontWeight: 600 }}>{value}{suffix}</span>
                </div>
              ))}
            </div>
          </Panel>

          {/* Model output */}
          <Panel style={{ border: `1px solid ${homeColor}44` }}>
            <Label>Model output</Label>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8 }}>
              <span style={{ fontSize: 12, color: theme.muted }}>{homeTricode} win prob</span>
              <span style={{ fontSize: 28, fontWeight: 900, color: homeColor }}>{homeProb.toFixed(3)}</span>
            </div>
          </Panel>

          {/* Stats legend */}
          <Panel>
            <Label>Legend</Label>
            <div style={{ fontSize: 11, color: theme.muted, lineHeight: 1.8, marginTop: 8 }}>
              <div><span style={{ color: homeColor }}>■</span> Home team</div>
              <div><span style={{ color: awayColor }}>■</span> Away team</div>
              <div style={{ marginTop: 6 }}>Updates every 5 seconds via live NBA API.</div>
              <div style={{ marginTop: 4 }}>Probability from neural network trained on {'{'}2020–24{'}'} play-by-play data.</div>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
