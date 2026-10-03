import React, {useEffect, useRef, useState} from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './markdown-message.css';

function CodeBlock({children}) {
  const [status, setStatus] = useState('');
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);
  const code = React.Children.toArray(children)[0];
  const text = typeof code?.props?.children === 'string' ? code.props.children : '';
  const language = /language-([^\s]+)/.exec(code?.props?.className || '')?.[1];
  async function copy() {
    clearTimeout(timer.current);
    try {
      await navigator.clipboard.writeText(text);
      setStatus('已复制');
    } catch {
      setStatus('复制失败，请选中代码复制');
    }
    timer.current = setTimeout(() => setStatus(''), 2500);
  }
  return <div className="markdown-code-block">
    <div className="markdown-code-toolbar"><span>{language || '代码'}</span>
      <button type="button" onClick={copy}>复制代码</button></div>
    {status && <div className="markdown-copy-status" role="status">{status}</div>}
    <pre tabIndex={0} aria-label="代码内容">{children}</pre>
  </div>;
}

// Only explicit web/mail links can navigate. Relative paths remain readable text.
function safeUrl(url) {
  return /^(https?:\/\/|mailto:)/i.test(url) ? url : '';
}
const components = {
  pre: CodeBlock,
  a: ({href, children}) => href
    ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
    : <span>{children}</span>,
  img: ({alt}) => <span className="markdown-image-alt">[图片：{alt || '未提供说明'}]</span>,
  table: ({children}) => <div className="markdown-table-scroll" tabIndex={0} role="region" aria-label="表格，可横向滚动"><table>{children}</table></div>,
};

export default function MarkdownMessage({text}) {
  return <div className="markdown-message"><ReactMarkdown
    remarkPlugins={[remarkGfm]} skipHtml urlTransform={safeUrl} components={components}
  >{typeof text === 'string' ? text : ''}</ReactMarkdown></div>;
}
