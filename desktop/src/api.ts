export type ChainHead = {
  height: number;
  tip_hash: string | null;
  state_tip_hash: string | null;
  canonical_tip_hash: string | null;
  block_count: number;
  difficulty_bits: number;
  next_difficulty_bits: number | null;
  pending_transaction_count: number;
};

export type BalanceRow = {
  address: string;
  alias: string | null;
  balance: string;
};

export type BalancesResponse = {
  tip_hash: string | null;
  height: number;
  balances: BalanceRow[];
};

async function readApi<T>(apiPort: number, path: string): Promise<T> {
  return window.unccoinDesktop.fetchApi(apiPort, path) as Promise<T>;
}

export function readChainHead(apiPort: number): Promise<ChainHead> {
  return readApi<ChainHead>(apiPort, "/chain/head");
}

export function readBalances(apiPort: number): Promise<BalancesResponse> {
  return readApi<BalancesResponse>(apiPort, "/balances");
}
