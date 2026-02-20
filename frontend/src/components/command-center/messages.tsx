/**
 * Chat message components and banner elements.
 *
 * SystemMessage, UserMessage, TypingIndicator for the conversation thread.
 * ActiveSourceBanner + SettingsPopover for data source status.
 * InteractiveModeBanner for ad-hoc shipping mode.
 * WelcomeMessage for onboarding and example commands.
 */

import * as React from 'react';
import { useAppState, type ConversationMessage } from '@/hooks/useAppState';
import { cn, formatRelativeTime } from '@/lib/utils';
import { Package } from 'lucide-react';
import { PackageIcon, GearIcon, HardDriveIcon, CopyIcon, CheckIcon } from '@/components/ui/icons';
import { ShopifyIcon } from '@/components/ui/brand-icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

/** Copy-to-clipboard button with brief checkmark feedback. */
function CopyButton({ text }: { text: string }) {
  const [state, setState] = React.useState<'idle' | 'copied' | 'error'>('idle');

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState('copied');
      setTimeout(() => setState('idle'), 1500);
    } catch (err) {
      console.error('Failed to copy to clipboard:', err);
      setState('error');
      setTimeout(() => setState('idle'), 2000);
    }
  };

  return (
    <button
      onClick={handleCopy}
      className="absolute top-2 right-2 p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity bg-slate-800/80 hover:bg-slate-700 text-slate-400 hover:text-slate-200"
      title={state === 'error' ? 'Copy failed' : 'Copy to clipboard'}
    >
      {state === 'copied' ? (
        <CheckIcon className="w-3.5 h-3.5 text-green-400" />
      ) : state === 'error' ? (
        <span className="text-red-400 text-[10px] font-medium px-0.5">!</span>
      ) : (
        <CopyIcon className="w-3.5 h-3.5" />
      )}
    </button>
  );
}

/** System-generated chat message with avatar. */
export function SystemMessage({ message }: { message: ConversationMessage }) {
  return (
    <div className="flex gap-3 animate-fade-in-up">
      <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500/20 to-cyan-600/20 border border-cyan-500/30 flex items-center justify-center">
        <PackageIcon className="w-4 h-4 text-cyan-400" />
      </div>

      <div className="flex-1 space-y-2 relative group">
        <div className="message-system prose prose-invert max-w-none prose-sm prose-p:leading-relaxed prose-pre:bg-slate-800/50 prose-pre:border prose-pre:border-slate-700/50">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {message.content}
          </ReactMarkdown>
        </div>
        <CopyButton text={message.content} />

        <span className="text-[10px] font-mono text-slate-500">
          {formatRelativeTime(message.timestamp)}
        </span>
      </div>
    </div>
  );
}

/** User message in the chat thread. */
export function UserMessage({ message }: { message: ConversationMessage }) {
  return (
    <div className="flex gap-3 justify-end animate-fade-in-up">
      <div className="flex-1 space-y-2 flex flex-col items-end relative group">
        <div className="message-user">
          <p className="text-sm whitespace-pre-wrap">{message.content}</p>
        </div>
        <CopyButton text={message.content} />

        <span className="text-[10px] font-mono text-slate-500">
          {formatRelativeTime(message.timestamp)}
        </span>
      </div>
    </div>
  );
}

/** Animated typing indicator for agent processing. */
export function TypingIndicator() {
  return (
    <div className="flex gap-3 animate-fade-in">
      <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500/20 to-cyan-600/20 border border-cyan-500/30 flex items-center justify-center">
        <PackageIcon className="w-4 h-4 text-cyan-400" />
      </div>

      <div className="message-system py-3">
        <div className="typing-indicator">
          <span />
          <span />
          <span />
        </div>
      </div>
    </div>
  );
}

/** Button to open settings flyout from the banner. */
export function SettingsButton() {
  const { settingsFlyoutOpen, setSettingsFlyoutOpen } = useAppState();

  return (
    <button
      onClick={() => setSettingsFlyoutOpen(!settingsFlyoutOpen)}
      className={cn(
        "p-1.5 rounded transition-colors",
        settingsFlyoutOpen ? "bg-slate-700 text-white" : "hover:bg-slate-800 text-slate-400"
      )}
      title="Open settings"
    >
      <GearIcon className="w-4 h-4" />
    </button>
  );
}

/** Compact banner showing the currently active data source at the top of the chat area. */
export function ActiveSourceBanner() {
  const { activeSourceInfo } = useAppState();

  return (
    <div className="flex items-center gap-2 px-4 py-1.5 border-b border-border/50 bg-card/30">
      {activeSourceInfo && (
        <>
          <span className="w-1.5 h-1.5 rounded-full bg-success flex-shrink-0" />
          {activeSourceInfo.sourceKind === 'shopify' ? (
            <ShopifyIcon className="w-3.5 h-3.5 text-[#5BBF3D]" />
          ) : (
            <HardDriveIcon className="w-3.5 h-3.5 text-slate-400" />
          )}
          <span className="text-xs font-medium text-slate-300">
            {activeSourceInfo.label}
          </span>
          <span className="text-slate-600">&middot;</span>
          <span className="text-[10px] font-mono text-slate-500">
            {activeSourceInfo.detail}
          </span>
        </>
      )}
      <div className="ml-auto">
        <SettingsButton />
      </div>
    </div>
  );
}

/** Compact banner shown when interactive shipping mode is active. */
export function InteractiveModeBanner() {
  return (
    <div className="flex items-center gap-2 px-4 py-1.5 border-b border-amber-500/20 bg-amber-500/5">
      <span className="w-1.5 h-1.5 rounded-full bg-amber-400 flex-shrink-0" />
      <span className="text-xs font-medium text-amber-200">Single Shipment</span>
    </div>
  );
}

/** Welcome screen with workflow steps and example commands (context-aware). */
export function WelcomeMessage({
  onExampleClick,
  interactiveShipping = false,
}: {
  onExampleClick?: (text: string) => void;
  interactiveShipping?: boolean;
}) {
  const { activeSourceInfo } = useAppState();
  const isConnected = !!activeSourceInfo;

  const batchExamples = [
    { text: 'Ship all California orders using UPS Ground', desc: 'Filter by state' },
    { text: "Ship today's pending orders with 2nd Day Air", desc: 'Filter by status & date' },
    { text: 'Create shipments for orders over $100', desc: 'Filter by amount' },
  ];

  const interactiveExamples = [
    { text: 'Ship a 5lb box to John Smith at 123 Main St, Springfield IL 62704 via Ground', desc: 'Single shipment' },
    { text: 'Create a Next Day Air shipment to 456 Oak Ave, Austin TX 78701', desc: 'Express shipment' },
  ];

  const examples = interactiveShipping ? interactiveExamples : batchExamples;

  if (interactiveShipping) {
    return (
      <div className="flex flex-col items-center pt-12 text-center px-4 animate-fade-in">
        <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-primary mb-4">
          <Package className="h-6 w-6 text-primary-foreground" />
        </div>

        <h2 className="text-xl font-semibold text-foreground mb-2">
          Single Shipment
        </h2>

        <p className="text-sm text-slate-400 max-w-md mb-6">
          Create one shipment from scratch in natural language.
          <br />
          ShipAgent will ask for any missing required details.
        </p>

        <div className="space-y-3 w-full max-w-md">
          <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Click to try</p>
          <div className="space-y-2">
            {examples.map((example, i) => (
              <button
                key={i}
                onClick={() => onExampleClick?.(example.text)}
                className="w-full px-4 py-3 rounded-lg bg-slate-800/50 border border-slate-700/50 text-left hover:bg-slate-800 hover:border-slate-600 transition-colors group"
              >
                <p className="text-sm text-slate-300 group-hover:text-slate-100">"{example.text}"</p>
                <p className="text-[10px] text-slate-600 mt-0.5">{example.desc}</p>
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (!isConnected) {
    return (
      <div className="flex flex-col items-center pt-12 text-center px-4 animate-fade-in">
        <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-primary mb-4">
          <Package className="h-6 w-6 text-primary-foreground" />
        </div>

        <h2 className="text-xl font-semibold text-foreground mb-2">
          Welcome to ShipAgent
        </h2>

        <p className="text-sm text-slate-400 max-w-md mb-6">
          Natural language batch shipment processing powered by AI.
          <br />
          Connect a data source from the sidebar to get started.
        </p>

        <div className="grid grid-cols-3 gap-4 w-full max-w-lg mb-6">
          {[
            { step: '1', title: 'Connect', desc: 'File, database, or platform' },
            { step: '2', title: 'Describe', desc: 'Natural language command' },
            { step: '3', title: 'Ship', desc: 'Preview, approve, execute' },
          ].map((item) => (
            <div key={item.step} className="text-center">
              <div className="w-8 h-8 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center mx-auto mb-2">
                <span className="text-xs font-mono text-primary">{item.step}</span>
              </div>
              <p className="text-xs font-medium text-slate-200">{item.title}</p>
              <p className="text-[10px] text-slate-500">{item.desc}</p>
            </div>
          ))}
        </div>

        <div className="space-y-2 w-full max-w-md opacity-50">
          <p className="text-[10px] font-mono text-slate-600 uppercase tracking-wider">Example commands</p>
          <div className="space-y-1.5">
            {examples.map((example, i) => (
              <div
                key={i}
                className="px-3 py-2 rounded-lg bg-slate-800/30 border border-slate-800/50 text-left"
              >
                <p className="text-xs text-slate-500">"{example.text}"</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center pt-12 text-center px-4 animate-fade-in">
      <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-primary mb-4">
        <Package className="h-6 w-6 text-primary-foreground" />
      </div>

      <h2 className="text-xl font-semibold text-foreground mb-2">
        Ready to Ship
      </h2>

      <p className="text-sm text-slate-400 max-w-md mb-2">
        Connected to <span className="text-primary font-medium">{activeSourceInfo!.label}</span>
        <> · <span className="text-slate-500">{activeSourceInfo!.detail}</span></>
      </p>

      <p className="text-xs text-slate-500 max-w-md mb-6">
        Describe what you want to ship in natural language. ShipAgent will parse your intent,
        filter your data, and generate a preview for your approval.
      </p>

      <div className="space-y-3 w-full max-w-md">
        <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Click to try</p>
        <div className="space-y-2">
          {examples.map((example, i) => (
            <button
              key={i}
              onClick={() => onExampleClick?.(example.text)}
              className="w-full px-4 py-3 rounded-lg bg-slate-800/50 border border-slate-700/50 text-left hover:bg-slate-800 hover:border-slate-600 transition-colors group"
            >
              <p className="text-sm text-slate-300 group-hover:text-slate-100">"{example.text}"</p>
              <p className="text-[10px] text-slate-600 mt-0.5">{example.desc}</p>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
