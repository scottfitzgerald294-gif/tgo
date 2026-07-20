export type ProviderModelType = 'chat' | 'embedding';

export interface ProviderModelWithType {
  model_id: string;
  model_type: ProviderModelType;
}

export function mergeProviderModels(
  existingModels: ProviderModelWithType[],
  newModels: ProviderModelWithType[]
): ProviderModelWithType[] {
  const modelsById = new Map<string, ProviderModelWithType>();

  for (const model of existingModels) {
    modelsById.set(model.model_id, model);
  }

  for (const model of newModels) {
    modelsById.set(model.model_id, model);
  }

  return [...modelsById.values()];
}
