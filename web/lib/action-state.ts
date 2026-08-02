export interface ActionState {
  kind: "idle" | "success" | "error";
  message: string;
}

export const INITIAL_ACTION_STATE: ActionState = {
  kind: "idle",
  message: "",
};
