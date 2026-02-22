/**
 * ConnectionsSection - Settings accordion section for provider connections.
 *
 * Renders ProviderCards for UPS and Shopify with their credential forms.
 * Consumes provider connection state from useAppState.
 */

import * as React from 'react';
import { ChevronDown, Key, Plug } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAppState } from '@/hooks/useAppState';
import { deleteProviderConnection, disconnectProvider } from '@/lib/api';
import { ProviderCard } from './ProviderCard';
import { UPSConnectForm } from './UPSConnectForm';
import { ShopifyConnectForm } from './ShopifyConnectForm';
import { AnthropicKeyForm } from './AnthropicKeyForm';
import { ShopifyIcon } from '@/components/ui/brand-icons';

/** Simple inline UPS shield icon. */
function UPSIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
  );
}

interface ConnectionsSectionProps {
  isOpen: boolean;
  onToggle: () => void;
}

export function ConnectionsSection({ isOpen, onToggle }: ConnectionsSectionProps) {
  const {
    providerConnections,
    providerConnectionsLoading,
    refreshProviderConnections,
    credentialStatus,
    refreshCredentialStatus,
  } = useAppState();

  const [openProvider, setOpenProvider] = React.useState<string | null>(null);

  const upsConnections = providerConnections.filter((c) => c.provider === 'ups');
  const shopifyConnections = providerConnections.filter((c) => c.provider === 'shopify');

  const handleDelete = async (connectionKey: string) => {
    await deleteProviderConnection(connectionKey);
    refreshProviderConnections();
  };

  const handleDisconnect = async (connectionKey: string) => {
    await disconnectProvider(connectionKey);
    refreshProviderConnections();
  };

  const toggleProvider = (provider: string) => {
    setOpenProvider(openProvider === provider ? null : provider);
  };

  const totalConfigured =
    providerConnections.filter((c) => c.status !== 'disconnected').length +
    (credentialStatus?.anthropic_api_key ? 1 : 0);

  return (
    <div className="settings-section">
      <button
        className="settings-section-header"
        onClick={onToggle}
        aria-expanded={isOpen}
      >
        <div className="flex items-center gap-2">
          <Plug className="h-4 w-4 text-muted-foreground" />
          <span className="font-medium text-foreground">Connections</span>
          {totalConfigured > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-success/15 text-success border border-success/30">
              {totalConfigured} active
            </span>
          )}
          {providerConnectionsLoading && (
            <span className="block w-3 h-3 border-2 border-muted-foreground border-t-transparent rounded-full animate-spin" />
          )}
        </div>
        <ChevronDown
          className={cn(
            'h-4 w-4 text-muted-foreground transition-transform',
            isOpen && 'rotate-180'
          )}
        />
      </button>

      {isOpen && (
        <div className="settings-section-content space-y-2">
          {/* Anthropic API Key */}
          <div className="rounded-lg border border-border overflow-hidden">
            <button
              className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-muted/30 transition-colors"
              onClick={() => toggleProvider('anthropic')}
            >
              <div className="flex items-center gap-2">
                <Key className="h-4 w-4 text-[#D97706]" />
                <span className="text-xs font-medium text-foreground">Anthropic</span>
                {credentialStatus?.anthropic_api_key ? (
                  <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-success/15 text-success border border-success/30">
                    Configured
                  </span>
                ) : (
                  <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-warning/15 text-warning border border-warning/30">
                    Not configured
                  </span>
                )}
              </div>
              <ChevronDown
                className={cn(
                  'h-3.5 w-3.5 text-muted-foreground transition-transform',
                  openProvider === 'anthropic' && 'rotate-180'
                )}
              />
            </button>
            {openProvider === 'anthropic' && (
              <div className="px-3 pb-3 border-t border-border">
                <AnthropicKeyForm onSaved={refreshCredentialStatus} />
              </div>
            )}
          </div>

          {/* UPS Provider */}
          <ProviderCard
            providerName="UPS"
            icon={<UPSIcon className="h-4 w-4 text-[#FFB500]" />}
            connections={upsConnections}
            isOpen={openProvider === 'ups'}
            onToggle={() => toggleProvider('ups')}
            onDelete={handleDelete}
            onDisconnect={handleDisconnect}
            onValidated={refreshProviderConnections}
          >
            <UPSConnectForm
              existingConnections={upsConnections}
              onSaved={refreshProviderConnections}
            />
          </ProviderCard>

          {/* Shopify Provider */}
          <ProviderCard
            providerName="Shopify"
            icon={<ShopifyIcon className="h-4 w-4 text-[#5BBF3D]" />}
            connections={shopifyConnections}
            isOpen={openProvider === 'shopify'}
            onToggle={() => toggleProvider('shopify')}
            onDelete={handleDelete}
            onDisconnect={handleDisconnect}
            onValidated={refreshProviderConnections}
          >
            <ShopifyConnectForm
              existingConnection={shopifyConnections[0] ?? null}
              onSaved={refreshProviderConnections}
            />
          </ProviderCard>
        </div>
      )}
    </div>
  );
}

export default ConnectionsSection;
