import Mathlib.Data.Int.Basic
import Mathlib.Tactic

namespace Plain2MeTTaSemanticKernel

inductive PType where
  | bool
  | int
  deriving DecidableEq, Repr

inductive PValue where
  | bool (value : Bool)
  | int (value : Int)
  deriving DecidableEq, Repr

def HasType : PValue → PType → Prop
  | .bool _, .bool => True
  | .int _, .int => True
  | _, _ => False

structure Predicate where
  argumentType : PType
  holds : PValue → Prop

structure Contract where
  precondition : Predicate
  postcondition : Predicate

def Satisfies (contract : Contract) (input output : PValue) : Prop :=
  HasType input contract.precondition.argumentType ∧
  HasType output contract.postcondition.argumentType ∧
  contract.precondition.holds input → contract.postcondition.holds output

abbrev Trace := List PValue

def TraceWellTyped (trace : Trace) (type : PType) : Prop :=
  ∀ value ∈ trace, HasType value type

inductive Lowers : Contract → Contract → Prop
  | refl (contract : Contract) : Lowers contract contract

theorem lowering_preserves_satisfaction
    {source lowered : Contract} (lowering : Lowers source lowered)
    {input output : PValue} (satisfaction : Satisfies source input output) :
    Satisfies lowered input output := by
  cases lowering
  exact satisfaction

def nonnegative : Predicate where
  argumentType := .int
  holds
    | .int value => 0 ≤ value
    | _ => False

def pureNonnegativeContract : Contract where
  precondition := nonnegative
  postcondition := nonnegative

theorem pure_nonnegative_identity (value : Int) (hypothesis : 0 ≤ value) :
    Satisfies pureNonnegativeContract (.int value) (.int value) := by
  simp [Satisfies, HasType, pureNonnegativeContract, nonnegative, hypothesis]

structure CounterState where
  count : Nat
  deriving DecidableEq, Repr

def counterInvariant (bound : Nat) (state : CounterState) : Prop :=
  state.count ≤ bound

def counterStep (bound : Nat) (state : CounterState) : CounterState :=
  if state.count < bound then ⟨state.count + 1⟩ else state

theorem counter_step_preserves_invariant
    (bound : Nat) (state : CounterState)
    (invariant : counterInvariant bound state) :
    counterInvariant bound (counterStep bound state) := by
  simp only [counterStep]
  split <;> simp_all [counterInvariant]

theorem finite_two_step_trace_preserves_invariant
    (bound : Nat) (state : CounterState)
    (invariant : counterInvariant bound state) :
    counterInvariant bound (counterStep bound (counterStep bound state)) := by
  apply counter_step_preserves_invariant
  exact counter_step_preserves_invariant bound state invariant

example : Satisfies pureNonnegativeContract (.int 2) (.int 2) := by
  norm_num [Satisfies, HasType, pureNonnegativeContract, nonnegative]

end Plain2MeTTaSemanticKernel
