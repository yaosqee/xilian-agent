import React from 'react';

interface Props {
  role: 'user' | 'assistant';
  content: string;
  sticker?: { id: string; file: string };
  images?: string[];
}

export const MessageBubble: React.FC<Props> = React.memo(({ role, content, sticker, images }) => {
  const isXilian = role === 'assistant';
  return (
    <div className={`chat-message-row ${isXilian ? 'chat-message-row--xilian' : 'chat-message-row--partner'}`}>
      <div className={isXilian ? 'bubble-xilian' : 'bubble-partner'}>
        {/* 用户图片缩略图 */}
        {images && images.length > 0 && (
          <div style={{ marginBottom: 8 }}>
            {images.map((url, i) => (
              <img
                key={i}
                src={url}
                alt="发送的图片"
                style={{
                  maxWidth: 200,
                  maxHeight: 200,
                  borderRadius: 12,
                  border: '1px solid rgba(216, 180, 226, 0.3)',
                  objectFit: 'cover',
                }}
              />
            ))}
          </div>
        )}
        {/* 文字内容 */}
        {content || (
          <span style={{ opacity: 0.5, fontStyle: 'italic' }}>
            人家在想呢…
          </span>
        )}
        {/* 助手表情包 */}
        {isXilian && sticker && (
          <div style={{
            marginTop: 8,
            animation: 'stickerEnter 0.4s cubic-bezier(0.4, 0, 0.2, 1)',
          }}>
            <img
              src={sticker.file ? `/api/stickers/${sticker.file}` : `/api/stickers/${sticker.id}.webp`}
              alt={sticker.id}
              style={{
                maxWidth: 120,
                maxHeight: 120,
                borderRadius: 8,
              }}
              onError={(e) => {
                // 加载失败时隐藏
                (e.target as HTMLImageElement).style.display = 'none';
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
});
