// Loads the byte-level vector files from sdk/vectors (movetrics-fdt-vectors/1). The files
// are read as data only. This module is not a test file.

import { existsSync, readFileSync } from 'node:fs';

const VECTOR_DIR = new URL('../../vectors/', import.meta.url);

// The public repository (movetrics/sdk) ships the host-link vectors only: no pad-bus or pad-bootloader files, and
// ota_frames.json without its firmware-update cases. SOURCES.md exists only in the private tree.
export const PUBLIC_REPOSITORY = !existsSync(new URL('../../SOURCES.md', import.meta.url));
export const VECTOR_FILE_NAMES: readonly string[] = [
  'crc16.json',
  'host_frames.json',
  'stream_frames.json',
  'status.json',
  'ota_frames.json',
  ...(PUBLIC_REPOSITORY ? [] : ['pad_bus.json', 'boot_frames.json']),
];

export type DeviceReplyJson =
  | { readonly nack_code: number }
  | { readonly reply: 'command_reply' }
  | { readonly reply: 'none'; readonly reason: string };

export interface VectorExpect {
  readonly valid?: boolean;
  readonly command?: string;
  readonly payload_hex?: string;
  readonly device_reply?: DeviceReplyJson;
  readonly dispatched?: boolean;
  readonly reason?: string;
  readonly fields?: Readonly<Record<string, unknown>>;
  readonly reference_parser?: string;
  readonly reference_kind?: string;
}

// One bag for every file. Each file uses a subset of these keys (vectors/README.md, field reference).
export interface VectorCase {
  readonly id: string;
  readonly kind: 'anchor' | 'derived';
  readonly description: string;
  readonly source: string;
  readonly frame_hex?: string;
  readonly rx_messages_hex?: readonly string[];
  readonly expect?: VectorExpect;
  readonly expect_frame_hex?: string | null;
  readonly expect_error?: string;
  readonly would_be_frame_hex?: string;
  readonly command?: string;
  readonly address_hex?: string;
  readonly destination_hex?: string;
  readonly payload_hex?: string;
  readonly input_hex?: string;
  readonly crc_hex?: string;
  readonly stored_hex?: string;
  readonly crc_stored_hex?: string;
  readonly crc_covers?: { readonly first: number; readonly last: number };
  readonly fields?: Readonly<Record<string, unknown>>;
  readonly expect_length_class?: string;
  readonly records?: readonly Readonly<Record<string, unknown>>[];
}

export interface VectorFile {
  readonly schema: string;
  readonly file: string;
  readonly description: string;
  readonly cases: readonly VectorCase[];
}

export function loadVectors(fileName: string): VectorFile {
  const text = readFileSync(new URL(fileName, VECTOR_DIR), 'utf8');
  const parsed = JSON.parse(text) as VectorFile;
  if (parsed.schema !== 'movetrics-fdt-vectors/1' || parsed.file !== fileName) {
    throw new Error(`${fileName} does not match the movetrics-fdt-vectors/1 schema`);
  }
  return parsed;
}

export function vectorCase(id: string): VectorCase {
  for (const name of VECTOR_FILE_NAMES) {
    const found = loadVectors(name).cases.find((candidate) => candidate.id === id);
    if (found !== undefined) return found;
  }
  throw new Error(`no vector case named ${id}`);
}
