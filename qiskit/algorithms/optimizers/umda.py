# This code is part of Qiskit.
#
# (C) Copyright IBM 2018, 2020.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Univariate Marginal Distribution Algorithm (Estimation-of-Distribution-Algorithm)."""

from typing import Callable, List, Optional, Tuple
import numpy as np
from scipy.stats import norm
from qiskit.utils import algorithm_globals

from .optimizer import OptimizerResult, POINT
from .scipy_optimizer import SciPyOptimizer


class UMDA(SciPyOptimizer):
    """Continuous Univariate Marginal Distribution Algorithm (UMDA).

    UMDA [1] is a specific type of Estimation of Distribution Algorithm (EDA) where new individuals
    are sampled from univariate normal distributions and are updated in each iteration of the
    algorithm by the best individuals found in the previous iteration.

    .. seealso::

        This code and analysis where obtained from EDAspy Python package [2].

    EDAs are stochastic search algorithms and belongs to the family of the evolutionary algorithms.
    The main difference is that EDAs have a probabilistic model which is updated in each iteration
    from the best individuals of previous generations (elite selection). Depending on the complexity
    of the probabilistic model, EDAs can be classified in a different way. In this case, UMDA is a
    univariate EDA as the embedded probabilistic model is univariate.

    UMDA has been compared to some of the already implemented algorithms in Qiskit library to
    optimize the parameters of a Variational algorithm such as QAOA or VQE and competitive results
    have been obtained [1]. UMDA seems to provide very good solutions for those circuits in which
    the number of layers is not big.

    The optimization process can be personalized depending on the paremeters chosen in the
    initialization. The main parameter is the population size. As bigger it is, the performance
    will be better. However, this increases the complexity of the algorithm and the runtime will
    be much heavier. In the work [1] different experiments have been performed where population
    size has been set to 20 - 30.

    .. note::

        The UMDA implementation has more parameter but these have been set in the initialization
        for better understanding of the user. For example, ``\alpha`` parameter has been set to 0.5
        and is the percentage of the population which is selected in each iteration to update the
        probabilistic model.


    Example:

        This short example runs UMDA for a toy example of the MAX-CUT problem.

        .. code-block:: python

            import numpy as np
            import networkx as nx
            from qiskit_optimization.applications import Maxcut, Tsp

            # Generating a graph of 4 nodes

            n = 4  # Number of nodes in graph
            G = nx.Graph()
            G.add_nodes_from(np.arange(0, n, 1))
            elist = [(0, 1, 1.0), (0, 2, 1.0), (0, 3, 1.0), (1, 2, 1.0), (2, 3, 1.0)]
            # tuple is (i,j,weight) where (i,j) is the edge
            G.add_weighted_edges_from(elist)

            # Computing the weight matrix from the random graph
            w = np.zeros([n, n])
            for i in range(n):
                for j in range(n):
                    temp = G.get_edge_data(i, j, default=0)
                    if temp != 0:
                        w[i, j] = temp["weight"]
            print(w)

            max_cut = Maxcut(w)
            qp = max_cut.to_quadratic_program()
            print(qp.export_as_lp_string())
            qubitOp, offset = qp.to_ising()

            # Run the algorithm

            algorithm_globals.random_seed = 123
            seed = 10598
            backend = Aer.get_backend("aer_simulator_statevector")
            quantum_instance = QuantumInstance(backend, seed_simulator=seed, seed_transpiler=seed)

            p = 2  # Toy example: 2 layers with 2 parameters in each layer: 4 variables

            opt = UMDA(maxiter=100, size_gen=20, n_variables=p*2, disp=True)

            backend = Aer.get_backend('statevector_simulator')
            vqe = QAOA(opt,
                       quantum_instance=QuantumInstance(backend=backend),
                       reps=p)

            result = vqe.compute_minimum_eigenvalue(operator=qubit_op)

        If it is desired to modify the percentage of individuals considered to update the
        probabilistic model, then this code can be used. Here for example we set the 60% instead
        of the 50% predefined.

        .. code-block:: python

            opt = UMDA(maxiter=100, size_gen=20, n_variables=p*2, alpha = 0.6, disp=True)

            backend = Aer.get_backend('statevector_simulator')
            vqe = QAOA(opt,
                       quantum_instance=QuantumInstance(backend=backend),
                       reps=p)

            result = vqe.compute_minimum_eigenvalue(operator=qubit_op)


    References:

        [1]: Vicente P. Soloviev, Pedro Larrañaga and Concha Bielza (2022, July). Quantum Parametric
        Circuit Optimization with Estimation of Distribution Algorithms. In 2022 The Genetic and
        Evolutionary Computation Conference (GECCO). DOI: https://doi.org/10.1145/3520304.3533963

        [2]: Vicente P. Soloviev. Python package EDAspy.
        https://github.com/VicentePerezSoloviev/EDAspy.
    """

    ELITE_FACTOR = 0.4
    STD_BOUND = 0.3

    # setting = "---"

    def __init__(
        self, maxiter: int, size_gen: int, n_variables: int, alpha: float = 0.5, disp: bool = False
    ) -> None:
        r"""
        Args:
            maxiter: Maximum number of function evaluations.
            size_gen: Population size of each generation.
            n_variables: Number of variables to be optimized. For example in QAOA the number of variables
            is 2p, where p is the number of layers of the circuit.
            alpha: Percentage [0, 1] of the population to be selected as elite selection.
            disp: Set to True to print convergence messages.
        """

        self.__disp = disp
        self.__size_gen = size_gen
        self.__max_iter = maxiter
        self.__alpha = alpha
        self.__n_variables = n_variables
        self.__vector = self._initialization()
        self.__dead_iter = self.__max_iter / 5

        self.__best_mae_global = 999999999999
        self.__truncation_length = int(size_gen * alpha)

        # initialization of generation
        self.__generation = algorithm_globals.random.normal(
            self.__vector[0, :], self.__vector[1, :], [self.__size_gen, self.__n_variables]
        )

        super().__init__(method="UMDA")

        self.__best_ind_global = 9999999
        self.__history = []
        self.__evaluations = np.array(0)

    def _initialization(self):
        vector = np.zeros((4, self.__n_variables))

        vector[0, :] = np.pi  # mu
        vector[1, :] = 0.5  # std
        vector[2, :] = 0  # min
        vector[3, :] = np.pi * 2  # max

        return vector

    # build a generation of size SIZE_GEN from prob vector
    def _new_generation(self):
        """Build a new generation sampled from the vector of probabilities.
        Updates the generation pandas dataframe
        """

        gen = algorithm_globals.random.normal(
            self.__vector[0, :], self.__vector[1, :], [self.__size_gen, self.__n_variables]
        )

        self.__generation = self.__generation[: int(self.ELITE_FACTOR * len(self.__generation))]
        self.__generation = np.vstack((self.__generation, gen))

    # truncate the generation at alpha percent
    def _truncation(self):
        """Selection of the best individuals of the actual generation.
        Updates the generation by selecting the best individuals.
        """
        best_indices = self.__evaluations.argsort()[: self.__truncation_length]
        self.__generation = self.__generation[best_indices, :]
        self.__evaluations = np.take(self.__evaluations, best_indices)

    # check each individual of the generation
    def _check_generation(self, objective_function):
        """Check the cost of each individual in the cost function implemented by the user."""
        self.__evaluations = np.apply_along_axis(objective_function, 1, self.__generation)

    # update the probability vector
    def _update_vector(self):
        """From the best individuals update the vector of normal distributions in order to the next
        generation can sample from it. Update the vector of normal distributions
        """

        for i in range(self.__n_variables):
            self.__vector[0, i], self.__vector[1, i] = norm.fit(self.__generation[:, i])
            if self.__vector[1, i] < self.STD_BOUND:
                self.__vector[1, i] = self.STD_BOUND

    def minimize(
        self,
        fun: Callable[[POINT], float],
        x0: POINT,
        jac: Optional[Callable[[POINT], POINT]] = None,
        bounds: Optional[List[Tuple[float, float]]] = None,
    ) -> OptimizerResult:

        self.__history = []
        not_better = 0
        result = OptimizerResult()

        for _ in range(self.__max_iter):
            self._check_generation(fun)
            self._truncation()
            self._update_vector()

            best_mae_local = min(self.__evaluations)

            self.__history.append(best_mae_local)
            best_ind_local = np.where(self.__evaluations == best_mae_local)[0][0]
            best_ind_local = self.__generation[best_ind_local]

            # update the best values ever
            if best_mae_local < self.__best_mae_global:
                self.__best_mae_global = best_mae_local
                self.__best_ind_global = best_ind_local
                not_better = 0

            else:
                not_better += 1
                if not_better == self.__dead_iter:
                    break

            self._new_generation()

        result.x = self.__best_ind_global
        result.fun = self.__best_mae_global
        result.nfev = len(self.__history) * self.__size_gen

        if self.__disp:
            print("\tNFVALS = " + str(result.nfev) + " F = " + str(result.fun))
            print("\tX = " + str(result.x))

        return result

    @property
    def disp(self):
        return self.__disp

    @disp.setter
    def disp(self, value: bool):
        self.__disp = value

    @property
    def size_gen(self):
        return self.__size_gen

    @size_gen.setter
    def size_gen(self, value: int):
        self.__size_gen = value

    @property
    def max_iter(self):
        return self.__max_iter

    @max_iter.setter
    def max_iter(self, value: int):
        self.__max_iter = value

    @property
    def alpha(self):
        return self.__alpha

    @alpha.setter
    def alpha(self, value: int):
        self.__alpha = value

    @property
    def n_variables(self):
        return self.__n_variables

    @n_variables.setter
    def n_variables(self, value: int):
        self.__n_variables = value

    @property
    def dead_iter(self):
        return self.__dead_iter

    @dead_iter.setter
    def dead_iter(self, value: int):
        self.__dead_iter = value

    @property
    def best_mae_global(self):
        return self.__best_mae_global

    @best_mae_global.setter
    def best_mae_global(self, value: int):
        self.__best_mae_global = value

    @property
    def best_ind_global(self):
        return self.__best_ind_global

    @property
    def generation(self):
        return self.__generation

    @generation.setter
    def generation(self, value: np.array):
        self.__generation = value

    @property
    def history(self):
        return self.__history
