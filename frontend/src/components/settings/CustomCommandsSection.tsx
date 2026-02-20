/**
 * Custom Commands Section - Settings accordion section.
 *
 * Features inline editor with expandable list, add/edit/delete,
 * and name validation.
 */

import * as React from 'react';
import { ChevronDown, Terminal, Plus, Edit2, Trash2, X, Check } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { useAppState } from '@/hooks/useAppState';
import * as api from '@/lib/api';
import type { CustomCommand } from '@/types/api';

// Name validation regex (lowercase, numbers, hyphens only)
const COMMAND_NAME_REGEX = /^[a-z][a-z0-9-]*$/;

interface CustomCommandsSectionProps {
  isOpen: boolean;
  onToggle: () => void;
}

export function CustomCommandsSection({
  isOpen,
  onToggle,
}: CustomCommandsSectionProps) {
  const { customCommands, refreshCommands } = useAppState();

  // State
  const [expandedCommand, setExpandedCommand] = React.useState<string | null>(null);
  const [isCreating, setIsCreating] = React.useState(false);
  const [isLoading, setIsLoading] = React.useState(false);
  const [deleteConfirm, setDeleteConfirm] = React.useState<string | null>(null);

  // Form state
  const [formName, setFormName] = React.useState('');
  const [formDescription, setFormDescription] = React.useState('');
  const [formBody, setFormBody] = React.useState('');
  const [formError, setFormError] = React.useState<string | null>(null);

  const existingNames = new Set(customCommands.map((c) => c.name));

  const validateName = (name: string): string | null => {
    if (!name) return 'Name is required';
    if (!COMMAND_NAME_REGEX.test(name)) {
      return 'Name must start with lowercase letter and contain only lowercase letters, numbers, and hyphens';
    }
    if (name.length > 50) {
      return 'Name must be 50 characters or less';
    }
    return null;
  };

  const resetForm = () => {
    setFormName('');
    setFormDescription('');
    setFormBody('');
    setFormError(null);
  };

  const handleStartCreate = () => {
    resetForm();
    setIsCreating(true);
    setExpandedCommand(null);
  };

  const handleStartEdit = (cmd: CustomCommand) => {
    setFormName(cmd.name);
    setFormDescription(cmd.description || '');
    setFormBody(cmd.body);
    setFormError(null);
    setExpandedCommand(cmd.id);
    setIsCreating(false);
  };

  const handleCancel = () => {
    resetForm();
    setExpandedCommand(null);
    setIsCreating(false);
  };

  const handleSaveNew = async () => {
    const nameError = validateName(formName);
    if (nameError) {
      setFormError(nameError);
      return;
    }
    if (existingNames.has(formName)) {
      setFormError(`Command /${formName} already exists`);
      return;
    }
    if (!formBody.trim()) {
      setFormError('Command body is required');
      return;
    }

    setIsLoading(true);
    try {
      await api.createCommand({
        name: formName,
        description: formDescription || undefined,
        body: formBody,
      });
      await refreshCommands();
      resetForm();
      setIsCreating(false);
    } catch (error) {
      console.error('Failed to create command:', error);
      setFormError('Failed to create command');
    } finally {
      setIsLoading(false);
    }
  };

  const handleSaveEdit = async (cmd: CustomCommand) => {
    const nameError = validateName(formName);
    if (nameError) {
      setFormError(nameError);
      return;
    }
    // Check for duplicate name (excluding current command)
    if (formName !== cmd.name && existingNames.has(formName)) {
      setFormError(`Command /${formName} already exists`);
      return;
    }
    if (!formBody.trim()) {
      setFormError('Command body is required');
      return;
    }

    setIsLoading(true);
    try {
      await api.updateCommand(cmd.id, {
        name: formName !== cmd.name ? formName : undefined,
        description: formDescription !== (cmd.description || '') ? formDescription || undefined : undefined,
        body: formBody !== cmd.body ? formBody : undefined,
      });
      await refreshCommands();
      resetForm();
      setExpandedCommand(null);
    } catch (error) {
      console.error('Failed to update command:', error);
      setFormError('Failed to update command');
    } finally {
      setIsLoading(false);
    }
  };

  const handleDelete = async (commandId: string) => {
    setIsLoading(true);
    try {
      await api.deleteCommand(commandId);
      await refreshCommands();
      setDeleteConfirm(null);
    } catch (error) {
      console.error('Failed to delete command:', error);
    } finally {
      setIsLoading(false);
    }
  };

  // Render command list item
  const renderCommandItem = (cmd: CustomCommand) => {
    const isEditing = expandedCommand === cmd.id;

    if (isEditing) {
      return (
        <div key={cmd.id} className="p-3 rounded-lg border border-border bg-card space-y-3">
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">/</span>
            <Input
              value={formName}
              onChange={(e) => setFormName(e.target.value.toLowerCase())}
              placeholder="command-name"
              className="font-mono h-8"
            />
          </div>
          <Input
            value={formDescription}
            onChange={(e) => setFormDescription(e.target.value)}
            placeholder="Description (optional)"
            className="h-8"
          />
          <textarea
            value={formBody}
            onChange={(e) => setFormBody(e.target.value)}
            placeholder="Command body - shipping instructions to expand..."
            rows={3}
            className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
          {formError && (
            <p className="text-xs text-destructive">{formError}</p>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={handleCancel}>
              <X className="h-3 w-3 mr-1" />
              Cancel
            </Button>
            <Button size="sm" onClick={() => handleSaveEdit(cmd)} disabled={isLoading}>
              <Check className="h-3 w-3 mr-1" />
              Save
            </Button>
          </div>
        </div>
      );
    }

    return (
      <div
        key={cmd.id}
        className="flex items-start justify-between p-2 rounded border border-border bg-card hover:bg-muted/30 transition-colors"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <code className="text-xs font-mono text-domain-paperless">
              /{cmd.name}
            </code>
            {cmd.description && (
              <span className="text-xs text-muted-foreground">
                — {cmd.description}
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-1 truncate">
            {cmd.body.slice(0, 60)}
            {cmd.body.length > 60 && '...'}
          </p>
        </div>
        <div className="flex items-center gap-1 ml-2">
          <Button variant="ghost" size="sm" onClick={() => handleStartEdit(cmd)}>
            <Edit2 className="h-3 w-3" />
          </Button>
          {deleteConfirm === cmd.id ? (
            <div className="flex items-center gap-1">
              <Button
                variant="destructive"
                size="sm"
                onClick={() => handleDelete(cmd.id)}
                disabled={isLoading}
              >
                Confirm
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setDeleteConfirm(null)}>
                <X className="h-3 w-3" />
              </Button>
            </div>
          ) : (
            <Button variant="ghost" size="sm" onClick={() => setDeleteConfirm(cmd.id)}>
              <Trash2 className="h-3 w-3" />
            </Button>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="settings-section">
      <button
        className="settings-section-header"
        onClick={onToggle}
        aria-expanded={isOpen}
      >
        <div className="flex items-center gap-2">
          <Terminal className="h-4 w-4 text-muted-foreground" />
          <span className="font-medium text-foreground">Custom Commands</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">
            {customCommands.length} commands
          </span>
          <ChevronDown
            className={`h-4 w-4 text-muted-foreground transition-transform ${
              isOpen ? 'rotate-180' : ''
            }`}
          />
        </div>
      </button>

      {isOpen && (
        <div className="settings-section-content space-y-3">
          {/* Command list */}
          {customCommands.length > 0 && (
            <div className="max-h-64 overflow-y-auto space-y-2">
              {customCommands.map(renderCommandItem)}
            </div>
          )}

          {/* Empty state */}
          {customCommands.length === 0 && !isCreating && (
            <p className="text-xs text-muted-foreground text-center py-2">
              No custom commands yet. Create shortcuts for common shipping instructions.
            </p>
          )}

          {/* Create new form */}
          {isCreating && (
            <div className="p-3 rounded-lg border border-dashed border-primary bg-primary/5 space-y-3">
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground">/</span>
                <Input
                  value={formName}
                  onChange={(e) => setFormName(e.target.value.toLowerCase())}
                  placeholder="command-name"
                  className="font-mono h-8"
                  autoFocus
                />
              </div>
              <Input
                value={formDescription}
                onChange={(e) => setFormDescription(e.target.value)}
                placeholder="Description (optional)"
                className="h-8"
              />
              <textarea
                value={formBody}
                onChange={(e) => setFormBody(e.target.value)}
                placeholder="Command body - shipping instructions to expand..."
                rows={3}
                className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              />
              {formError && (
                <p className="text-xs text-destructive">{formError}</p>
              )}
              <div className="flex justify-end gap-2">
                <Button variant="outline" size="sm" onClick={handleCancel}>
                  Cancel
                </Button>
                <Button size="sm" onClick={handleSaveNew} disabled={isLoading}>
                  <Plus className="h-3 w-3 mr-1" />
                  Create
                </Button>
              </div>
            </div>
          )}

          {/* Add button (when not creating) */}
          {!isCreating && (
            <button
              onClick={handleStartCreate}
              className="w-full flex items-center gap-2 px-3 py-2 rounded-md border border-dashed border-border hover:border-primary hover:bg-primary/5 transition-colors"
            >
              <Plus className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm text-muted-foreground">Create new command</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default CustomCommandsSection;
