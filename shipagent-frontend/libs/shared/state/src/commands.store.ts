/**
 * CommandsStore — Custom slash commands state.
 *
 * Manages user-defined slash commands that expand to shipping instructions.
 * Hydrated on app init and refreshed after mutations.
 */

import { signalStore, withState, withMethods, patchState } from '@ngrx/signals';
import type { CustomCommand } from '@shipagent/shared-types';

export interface CommandsState {
  /** All user-defined custom slash commands. */
  customCommands: CustomCommand[];
}

const initialState: CommandsState = {
  customCommands: [],
};

export const CommandsStore = signalStore(
  { providedIn: 'root' },
  withState<CommandsState>(initialState),
  withMethods((store) => ({
    /** Replace all commands (full refresh from API). */
    setCommands(commands: CustomCommand[]): void {
      patchState(store, { customCommands: commands });
    },

    /** Optimistically add a new command. */
    addCommand(cmd: CustomCommand): void {
      patchState(store, (s) => ({ customCommands: [...s.customCommands, cmd] }));
    },

    /** Optimistically update a command by ID. */
    updateCommand(id: string, updated: Partial<CustomCommand>): void {
      patchState(store, (s) => ({
        customCommands: s.customCommands.map((c) =>
          c.id === id ? { ...c, ...updated } : c,
        ),
      }));
    },

    /** Optimistically remove a command by ID. */
    removeCommand(id: string): void {
      patchState(store, (s) => ({
        customCommands: s.customCommands.filter((c) => c.id !== id),
      }));
    },
  })),
);
