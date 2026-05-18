import React, { useEffect, useState } from 'react';

interface Note {
  id: number;
  kind: string;
  content: string;
  tags: string | null;
  created_at: number;
}

interface Task {
  id: number;
  title: string;
  details: string;
  priority: number;
  status: string;
  due_at: number;
}

interface AutoListItem {
  date: string;
  mood_summary?: string;
  word_count?: number;
}

const BASE = '/api';

const Empty: React.FC<{ text: string }> = ({ text }) => (
  <div style={{ color: 'var(--color-text-muted)', textAlign: 'center', padding: 24, fontSize: 13 }}>{text}</div>
);

export const NotebookPanel: React.FC = () => {
  const [tab, setTab] = useState<'notes' | 'diary' | 'tasks'>('notes');
  const [notes, setNotes] = useState<Note[]>([]);
  const [diaries, setDiaries] = useState<AutoListItem[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    if (tab === 'notes') fetchNotes();
    if (tab === 'diary') fetchDiaries();
    if (tab === 'tasks') fetchTasks();
  }, [tab]);

  const safeJson = async (res: Response) => {
    try { return await res.json(); }
    catch { return []; }
  };

  const fetchNotes = async () => {
    try {
      const data = await safeJson(await fetch(`${BASE}/notebook/notes?limit=20`));
      setNotes(Array.isArray(data) ? data : []);
    } catch (e) { setNotes([]); }
  };

  const fetchDiaries = async () => {
    try {
      const data = await safeJson(await fetch(`${BASE}/autobiography/list?limit=30`));
      const entries = data?.entries || (Array.isArray(data) ? data : []);
      setDiaries(entries);
    } catch (e) { setDiaries([]); }
  };

  const fetchTasks = async () => {
    try {
      const data = await safeJson(await fetch(`${BASE}/notebook/tasks`));
      setTasks(Array.isArray(data) ? data : []);
    } catch (e) { setTasks([]); }
  };

  const markComplete = async (id: number) => {
    try {
      await fetch(`${BASE}/notebook/tasks/${id}/complete`, { method: 'POST' });
      fetchTasks();
    } catch {}
  };

  const deleteNote = async (id: number) => {
    if (!window.confirm('确定要删除这条笔记吗？删除后无法恢复。')) return;
    try {
      await fetch(`${BASE}/notebook/notes/${id}`, { method: 'DELETE' });
      fetchNotes();
    } catch {}
  };

  const deleteTask = async (id: number) => {
    if (!window.confirm('确定要删除这个任务吗？删除后无法恢复。')) return;
    try {
      await fetch(`${BASE}/notebook/tasks/${id}`, { method: 'DELETE' });
      fetchTasks();
    } catch {}
  };

  const tabStyle = (t: typeof tab): React.CSSProperties => ({
    padding: '6px 16px',
    background: tab === t ? 'rgba(255, 183, 197, 0.15)' : 'transparent',
    color: tab === t ? 'var(--color-pink-dark)' : 'var(--color-text-dim)',
    border: 'none', borderRadius: 8, cursor: 'pointer', fontSize: 13,
    fontWeight: tab === t ? 600 : 400,
  });

  const cardStyle: React.CSSProperties = {
    background: 'rgba(255, 255, 255, 0.4)',
    borderRadius: 10, padding: '10px 14px', fontSize: 13,
    border: '1px solid rgba(200, 180, 210, 0.2)',
  };

  return (
    <div>
      <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 10, color: 'var(--color-text)' }}>
        昔涟的笔记本
      </h3>
      <div style={{ display: 'flex', gap: 6, marginBottom: 14 }}>
        <button style={tabStyle('notes')} onClick={() => setTab('notes')}>笔记</button>
        <button style={tabStyle('diary')} onClick={() => setTab('diary')}>日记</button>
        <button style={tabStyle('tasks')} onClick={() => setTab('tasks')}>任务</button>
      </div>

      {error && <Empty text={error} />}

      {tab === 'notes' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {notes.map((n) => (
            <div key={n.id} style={cardStyle}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div style={{ color: 'var(--color-text)', flex: 1 }}>{n.content || '(空)'}</div>
                <button
                  onClick={() => deleteNote(n.id)}
                  title="删除笔记"
                  style={{
                    background: 'transparent', border: 'none', color: 'var(--color-text-muted)',
                    cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: '0 0 0 8px',
                    opacity: 0.5, transition: 'opacity 0.2s',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.opacity = '1')}
                  onMouseLeave={(e) => (e.currentTarget.style.opacity = '0.5')}
                >
                  ×
                </button>
              </div>
              {n.tags && (
                <div style={{ color: 'var(--color-text-dim)', fontSize: 11, marginTop: 4 }}>
                  {(() => { try { return typeof n.tags === 'string' ? JSON.parse(n.tags).map((t: string) => `#${t} `).join('') : ''; } catch { return ''; } })()}
                </div>
              )}
            </div>
          ))}
          {notes.length === 0 && <Empty text="暂无笔记" />}
        </div>
      )}

      {tab === 'diary' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {diaries.length === 0 ? (
            <Empty text="昔涟还没有开始写日记呢~" />
          ) : (
            diaries.map((d) => (
              <div key={d.date} style={cardStyle}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                  <span style={{ color: 'var(--color-text)', fontSize: 13, fontWeight: 500 }}>
                    {d.date}
                  </span>
                  <span style={{ color: 'var(--color-text-dim)', fontSize: 11 }}>
                    {d.word_count ? `${d.word_count} 字` : ''}
                  </span>
                </div>
                {d.mood_summary && (
                  <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>
                    {d.mood_summary}
                  </div>
                )}
                <div style={{ color: 'var(--color-text-dim)', fontSize: 11, marginTop: 4 }}>
                  在「自传」面板阅读全文 →
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {tab === 'tasks' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {tasks.map((t) => (
            <div key={t.id} style={{
              ...cardStyle,
              borderLeft: `3px solid ${t.priority >= 2 ? 'var(--color-pink-dark)' : t.priority >= 1 ? '#f0a020' : '#40a040'}`,
              opacity: t.status === 'done' ? 0.5 : 1,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ color: 'var(--color-text)' }}>{t.title}</span>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  {t.status === 'pending' && (
                    <button onClick={() => markComplete(t.id)} style={{
                      background: 'rgba(100, 180, 100, 0.15)', color: '#40a040',
                      border: 'none', borderRadius: 4, padding: '2px 8px', cursor: 'pointer', fontSize: 11,
                    }}>
                      完成
                    </button>
                  )}
                  <button
                    onClick={() => deleteTask(t.id)}
                    title="删除任务"
                    style={{
                      background: 'transparent', border: 'none', color: 'var(--color-text-muted)',
                      cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: 0,
                      opacity: 0.5, transition: 'opacity 0.2s',
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.opacity = '1')}
                    onMouseLeave={(e) => (e.currentTarget.style.opacity = '0.5')}
                  >
                    ×
                  </button>
                </div>
              </div>
            </div>
          ))}
          {tasks.length === 0 && <Empty text="暂无待办任务" />}
        </div>
      )}
    </div>
  );
};
