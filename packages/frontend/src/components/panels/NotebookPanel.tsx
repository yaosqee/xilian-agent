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

export const NotebookPanel: React.FC = () => {
  const [tab, setTab] = useState<'notes' | 'diary' | 'tasks'>('notes');
  const [notes, setNotes] = useState<Note[]>([]);
  const [diaries, setDiaries] = useState<Note[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);

  useEffect(() => {
    if (tab === 'notes') fetchNotes();
    if (tab === 'diary') fetchDiaries();
    if (tab === 'tasks') fetchTasks();
  }, [tab]);

  const fetchNotes = async () => {
    try {
      const res = await fetch('/api/notebook/notes?limit=20');
      setNotes(await res.json());
    } catch {}
  };

  const fetchDiaries = async () => {
    try {
      const res = await fetch('/api/notebook/diary/list?limit=30');
      setDiaries(await res.json());
    } catch {}
  };

  const fetchTasks = async () => {
    try {
      const res = await fetch('/api/notebook/tasks');
      setTasks(await res.json());
    } catch {}
  };

  const markComplete = async (id: number) => {
    await fetch(`/api/notebook/tasks/${id}/complete`, { method: 'POST' });
    fetchTasks();
  };

  const tabStyle = (t: typeof tab) => ({
    padding: '6px 16px',
    background: tab === t ? '#2a2a3e' : 'transparent',
    color: tab === t ? '#f0c0d0' : '#888',
    border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 13,
  });

  return (
    <div style={{ padding: 16, overflowY: 'auto', height: '100%' }}>
      <h3 style={{ color: '#f0c0d0', marginBottom: 12 }}>昔涟的笔记本</h3>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <button style={tabStyle('notes')} onClick={() => setTab('notes')}>📝 笔记</button>
        <button style={tabStyle('diary')} onClick={() => setTab('diary')}>📖 日记</button>
        <button style={tabStyle('tasks')} onClick={() => setTab('tasks')}>⏰ 任务</button>
      </div>

      {tab === 'notes' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {notes.map((n) => (
            <div key={n.id} style={{
              background: '#15152a', borderRadius: 6, padding: '10px 14px', fontSize: 13,
            }}>
              <div style={{ color: '#ccc' }}>{n.content}</div>
              {n.tags && (
                <div style={{ color: '#666', fontSize: 11, marginTop: 4 }}>
                  {JSON.parse(n.tags).map((t: string) => `#${t} `)}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {tab === 'diary' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {diaries.map((d) => (
            <div key={d.id} style={{
              background: '#15152a', borderRadius: 6, padding: '10px 14px', fontSize: 13,
            }}>
              <div style={{ color: '#999', fontSize: 11, marginBottom: 4 }}>
                {new Date(d.created_at * 1000).toLocaleDateString('zh-CN')}
              </div>
              <div style={{ color: '#ccc' }}>
                {(d as any).preview || d.content?.slice(0, 80)}
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === 'tasks' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {tasks.map((t) => (
            <div key={t.id} style={{
              background: '#15152a', borderRadius: 6, padding: '10px 14px',
              borderLeft: `3px solid ${t.priority >= 2 ? '#d04040' : t.priority >= 1 ? '#f0a020' : '#40a040'}`,
              fontSize: 13, opacity: t.status === 'done' ? 0.5 : 1,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: '#ccc' }}>{t.title}</span>
                {t.status === 'pending' && (
                  <button
                    onClick={() => markComplete(t.id)}
                    style={{
                      background: '#2a4a2a', color: '#40a040', border: 'none',
                      borderRadius: 3, padding: '2px 8px', cursor: 'pointer', fontSize: 11,
                    }}
                  >
                    完成
                  </button>
                )}
              </div>
            </div>
          ))}
          {tasks.length === 0 && (
            <div style={{ color: '#666', textAlign: 'center', padding: 24 }}>
              暂无待办任务
            </div>
          )}
        </div>
      )}
    </div>
  );
};
