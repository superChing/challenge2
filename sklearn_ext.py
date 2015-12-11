# coding: utf-8
import itertools
from collections import defaultdict

import numpy as np
import pandas as pd
from sklearn.base import TransformerMixin, BaseEstimator
from sklearn.preprocessing import LabelEncoder
import logging

class TimeSeriesCVSplit:
    """data split for cross validation in **forecasting** task.

    What it differs from KFolds is that :
        1. validation folds may overlapping,
        2. train folds never exceed over validation in terms of time.
            i.e. the index lates than validation's are dropped.

    Args:
        timeindex (list[int]):  train's timeindex, shoud be integers.
        vali_len (int): len(time span of validation data), usually a test_time_span
        step (int): distance between every validaiton fold.
            step * n_folds= days covered by validation.
    Returns:
        position based index
    Example:
        In:
            dt=pd.Series(pd.date_range('2015/1/1','2015/1/5',unit='d'))
            dt=(dt-dt.min()).dt.days
            dt=dt.append(dt)  # dt x 2  = [1,2,3,4,5,1,2,3,4,5]
            [(x,y) for x,y in TimeSeriesCVSplit(dt,2,2,2)]

        Out:
            [(array([0, 1, 2, 5, 6, 7]), array([3, 4, 8, 9])),
             (array([0, 5]), array([1, 2, 6, 7]))]

    """

    def __init__(self, timeindex, n_folds, vali_len, step):
        self.n_folds = n_folds
        self.timeindex = pd.Series(timeindex)
        self.time_end = self.timeindex.max()
        self.vali = vali_len
        self.step = step

    def __iter__(self):
        t_end = None
        for i in range(self.n_folds):
            t_end = t_end - self.step if t_end else self.time_end + 1
            t_start = t_end - self.vali
            vali_idx = np.where(self.timeindex.between(t_start, t_end - 1))[0]  # between is inclusive
            train_idx = np.where(self.timeindex < t_start)[0]
            yield train_idx, vali_idx

    def __len__(self):
        return self.n_folds


class ObjIndexer(TransformerMixin, BaseEstimator):
    """turn object type columns of dataframe into random ordinal encoding.
    Args:
        ordinal : ??
    Returns:
        dataframe

    TODO:
        handle unseen values
        ordinal indexing if specified.
        unit test.
    """

    def __init__(self, columns=[]):
        self.columns = columns

    def fit(self, Xdf, y=None):
        if self.columns:
            _columns = self.columns
        else:
            _columns = filter(lambda x: Xdf[x].dtype.kind == "O", Xdf.columns)

        # random ordinal encoding for categorical columns
        random_indexers = {}
        for col in _columns:
            random_indexers[col] = LabelEncoder().fit(Xdf[col])
        self.random_indexers_ = random_indexers
        # #ohe
        # ohe_transformers = {}
        # for col in self.onehot_columns :
        #     x=Xdf[[col]]
        #     x=random_indexers[col].transform(x)
        #     ohe_transformers[col]= OneHotEncoder(sparse=False).fit(x)
        # self.ohe_transformers_=ohe_transformers

        # if self.ordinal: raise NotImplementedError()

        # from collections import defaultdict
        # transform=defaultdict(list)
        # for col,transf in random_indexers.items():
        #     transform[col].append(transf.transform)
        # # for col,transf in ohe_transformers.items():
        # #     transform[col].append(transf.transform)
        #
        # self.transform_ =transform
        return self

    def transform(self, Xdf, y=None):
        Xdf = Xdf.copy()
        for col, trans in self.random_indexers_.items():
            Xdf[col] = trans.transform(Xdf[col])

        # xs=[]
        # for col,transforms in self.transform_.items():
        #     x=Xdf[[col]]
        #     for f in transforms: x=f(x)
        #     xs.append(x if x.ndim==2 else x.reshape(-1,1))
        #
        # codes = np.hstack(xs)
        #
        # # remove original columns
        # Xdf = Xdf[Xdf.columns.difference(self.transform_.keys())]
        # X = np.hstack([Xdf.values, codes])
        # return X
        return Xdf


# TODO
# port it to comform sklearn API , so that we can use it in Pipeline. see RossmannStore utils.dynamic_features
# reference: rossmann_store.utils.dynamic_features
def state_duration_features(df):
    """ extract from categorical columns the time interval features.

    given a categorical column that represent a state of the subject 'along time'.
    extract feature of:
     1. time elapse since state start/last state switching
        column: TimeFromStart_{col}, TimeToEnd_{col}
     2. time interval/duration of state the subject are being in (that may take into account of future data).
        column: StateSpan_{col}

    **ASSUMPTION**:
        the dataframe's index is time increasing and continuous i.e. an common difference arithmetic sequence.

    Examples:
    In:
         df=pd.DataFrame([0,1,1,1,2,1],columns=['a'])
         print(state_duration_features(df))
    Out:
           TimeFromStart_a  StateSpan_a  TimeToEnd_a
        0              NaN          NaN            0
        1                0            3            2
        2                1            3            1
        3                2            3            0
        4                0            1            0
        5                0          NaN          NaN

    """
    # diff=df.index[1:].values-df.index[:-1].values
    # assert np.all(diff[1:]==diff[:-1] )# check it is common difference arithmetic sequence
    new_features = pd.DataFrame(index=df.index)
    from itertools import chain
    for col in df.columns:
        gen = itertools.groupby(df[col])
        groups = list(list(v) for k, v in gen)  # this is 'local' groupby ,e.x. [[1,1,1],[0,0]]

        elapse = np.array(list(x for x in chain.from_iterable(range(0, len(g)) for g in groups)),
                          np.float)  # bug np and pd dont eat chain
        elapse[:len(groups[0])] = np.nan
        new_features['TimeFromStart_' + col] = elapse

        span = np.array(list(chain.from_iterable([len(g)] * len(g) for g in groups)), np.float)
        span[:len(groups[0])] = np.nan
        span[-len(groups[-1]):] = np.nan
        new_features['StateSpan_' + col] = span

        to_end = np.array(list(chain.from_iterable(range(len(g) - 1, -1, -1) for g in groups)), np.float)
        to_end[-len(groups[-1]):] = np.nan
        new_features['TimeToEnd_' + col] = to_end

    return new_features


def event_features(df):
    """time elapse since the last k event

    the event time series is spikish state sequence, that doen't have state duration,
    e.g. Holiday by daily series . that 0 means no event, 1 means event.
    It can not be captured by status duration or elapse by using state_duration_features.

    add column: ElapseSinceLastEvent_{col}

    # TODO
    **CAVEAT:** for expedient I just set it = ElapseSinceLastState_{col}.shift(1),
        its not proper, wrong count happens two steps after events.

    **ASSUMPTION**:
        the dataframe's index is time increasing and continuous i.e. an common difference arithmetic sequence.

    Examples:
            df=pd.DataFrame([0,1,0,0,0,0,1,0,0,0],columns=['a'])
            print(event_features(df).T)
        Out:
                            0   1  2  3  4  5  6   7   8   9
            TimeFromLast_a NaN NaN  0  0  1  2  3   0   0   1
            TimeToNext_a     1   1  4  3  2  1  1 NaN NaN NaN
    """
    new_features = pd.DataFrame(index=df.index)
    from itertools import chain
    for col in df.columns:
        gen = itertools.groupby(df[col])
        groups = list(list(v) for k, v in gen)  # this is 'local' groupby ,e.x. [[1,1,1],[0,0]]
        elapse = np.array(list(chain.from_iterable(range(0, len(g)) for g in groups)),
                          np.float)  # bug np and pd dont eat chain
        elapse[:len(groups[0])] = np.nan
        new_features['TimeFromLast_' + col] = np.concatenate([[np.nan], elapse[:-1]])

        timeto = np.array(list(chain.from_iterable(range(len(g), 0, -1) for g in groups)),
                          np.float)  # bug np and pd dont eat chain
        timeto[-len(groups[-1]):] = np.nan
        new_features['TimeToNext_' + col] = timeto
    return new_features


def state_dynamic_features(df, lags=[]):
    """dynamic of states , it's not about time dynamic.

    1. switching dynamic -- what is last or next k states .
       columns with dynamic of only 2 states  is redundant , would be skipped.
       Add column {col}'_lag'{lag}
    2. dynamic of each specific state.
            If you want it then one hot encode it then numerical_dynamic_features.

    **ASSUMPTION**:
        the dataframe's index is time increasing and continuous i.e. an common difference arithmetic sequence.

    Args:
        lags (int): accept negative. lag 0 = original.
    Examples:
        df=pd.DataFrame([3,1,1,1,2],columns=['a'])
        print(state_dynamic_features(df,lags=[1,2]))
        Out:
               a_lag1  a_lag2
            0     NaN     NaN
            1       3     NaN
            2       3     NaN
            3       3     NaN
            4       1       3

    """
    new_features = pd.DataFrame(index=df.index)
    from itertools import chain
    for col in df.columns:
        gen = itertools.groupby(df[col])
        groups = list(list(v) for k, v in gen)  # this is 'local' groupby ,e.x. [[1,1],[0,0],[1]]
        # 2 state dynamic is redundant , skip
        if df[col].nunique(dropna=True) == 2:
            continue
        else:
            group_len = [len(g) for g in groups]
            group_values = [g[0] for g in groups]
            for lag in lags:
                if lag > 0:  # shift +
                    lag_group_values = [np.nan] * lag + group_values[:-lag]
                else:  # or -
                    lag_group_values = group_values[-lag:] + [np.nan] * -lag

                lag_values = chain.from_iterable([v] * length for length, v in zip(group_len, lag_group_values))
                lag_values = list(lag_values)
                new_features[col + '_lag' + str(lag)] = lag_values
    return new_features


def continuous_dynamic_features(df, lags=[]):
    """ extract from numerical columns the dynamic features.
    """
    new_features = pd.DataFrame(index=df.index)
    for col in df.columns:
        for lag in lags:
            lag_values = df[col].shift(lag).values
            new_features[col + '_lag' + str(lag)] = lag_values
    return new_features


def dynamic_prediction(self, Xdf, time, subject, y_column_name, force=True):
    """ recursive prediction
    Args:
        time (str or array-like): the dates of Xdf.  str for column name.
        subject (str or array-liek)
        Xdf ():
        force (boolean):
            True:   even the value in lag y have been filled, we still overwrite what we have predicted.
            False:  only fill y lag that are NaN.
                    so that you can fill desired value in advance, and the dynamic prediction would exploit it.
    **ASSUMPTION**:
        1. Xdf is dataframe with "{y_column_name}_lag{x}" where x is lag number.
    Exampels:
        class PredictMock:
            def predict(self,X):
                if X.isnull().any().any(): raise ValueError(X)
                return np.ones(len(X))
        df = pd.DataFrame({'ya': [1, 2, 3, 4, 5, 6],
                           'y_lag1': [1, 2, np.nan, np.nan, np.nan, np.nan],
                           'y_lag2': [1, 2, 3, 4, np.nan, np.nan]})
        time = [1, 1, 2, 2, 3, 3]
        subject = [1, 2, 1, 2, 1, 2]
        y = sklearn_ext.dynamic_prediction(PredictMock(), df, time, subject, 'y')
    TODO:
        Is it better if implemting it totally based on dataframe indexing ? with out pediction history list.
    """

    feature_cols = Xdf.columns
    df = Xdf.copy()
    if isinstance(time, str):
        try:
            df['_time'] = df[time]
        except:
            df['_time'] = df.index.get_level_values(time)
    else:
        df['_time'] = time
    # TODO check time is continuous
    if isinstance(subject, str):
        try:
            df['_subject'] = df[subject]
        except:
            df['_subject'] = df.index.get_level_values(subject)
    else:
        df['_subject'] = subject

    df['_yhat'] = pd.Series(index=df.index)
    # extract how many y_lag and how much
    col_lag = {}  # column -> n_lag mapping
    import re
    for col in df.columns:
        m = re.match(r'{}_lag(.+)'.format(y_column_name), col)
        if m and int(m.group(1)) > 0:
            col_lag[col] = -1 * int(m.group(1))

    import collections
    #  store -> prediction-history mapping, for retriving old y,
    #  another way is to use old y from dataframe, bu the indexing is abit complex.
    pred_history = collections.defaultdict(list)
    time_start = df._time.min()
    for t in sorted(df['_time'].unique()):
        # copy, because pandas dosen't have view and write on view.
        _X = df.loc[df['_time'] == t].copy()
        # fill nan from lag y
        for idx, x in _X.iterrows():
            _subject = x['_subject']
            for col in col_lag:
                if force:  # even the value in lag y have been filled, we still overwrite what we have predicted.
                    if (pd.Timestamp(t) - time_start).days >= abs(col_lag[col]):  # TODO type of time ?
                        _X.loc[idx, col] = pred_history[_subject][col_lag[col]]  # write on _X, a copy of df
                else:   # only fill y lag that are NaN.
                    if np.isnan(x[col]):
                        _X.loc[idx, col] = pred_history[_subject][col_lag[col]]
        yhat = self.predict(_X[feature_cols])
        _X['_yhat'] = yhat
        # fill prediction history
        for idx, x in _X.iterrows():
            pred_history[x['_subject']].append(x['_yhat'])
        # because _X is a copy of subset, wite the filled and yhat back.
        df.loc[_X.index, _X.columns] = _X
    assert len(Xdf) == sum(len(l) for l in pred_history.values())  # pred_history is in right length
    return df.reindex(Xdf.index)['_yhat']  # reindex to original input's


def _with_report(iterable, interval=1):
    import time
    count = 0
    for ele in iterable:
        start = time.time()
        X, Y, Xv, Yv = ele
        print('train : {} ~ {},\nvalidation : {} ~ {} '.format(
            X.index.min(), X.index.max(), Xv.index.min(), Xv.index.max()))
        yield ele
        count += 1
        if count >= interval:
            print('elapse {}s, work next.'.format(time.time() - start))
            count = 0


def gen_param(param_grid):
    """ex: param_grid={'a':[1,2],'b':[1,2]} """
    keys, values = zip(*param_grid.items())
    for v in itertools.product(*values):
        yield dict(zip(keys, v))  # a parameter


def grid_search_CV(estimator_class, param_grid, Xdf, Ydf, cv_spliter, losser, fit_params={}, verbose=False):
    """some grid search CV for early stopping"""
    folds = [(Xdf.iloc[train_idx], Ydf.iloc[train_idx], Xdf.iloc[vali_idx], Ydf.iloc[vali_idx]) for
             train_idx, vali_idx in cv_spliter]
    if verbose: folds = _with_report(folds)
    result = defaultdict(list)
    for param in gen_param(param_grid):
        for X, Y, Xv, Yv in folds:
            model = estimator_class(**param)
            model.fit(X, Y, **fit_params(X, Y, Xv, Yv))
            Yhat = model.predict(Xv)
            loss = losser(Yv, Yhat)
            result[tuple(param.items())].append(loss)

    return result

# ====== early-stop for RF =========
# def warm_start_early_stop(model,n_tree_to_add):
#     incre_errors=[]
#     for n in range(10, model.get_params()['n_estimators'] + 1,n_tree_to_add):
#         model.set_params(n_estimators=n,warm_start=True)
#         model.fit(X,y)
#         yhat = model.predict(Xv)
#         loss=utils.loss(np.expm1(yv),np.expm1( yhat))
#         incre_errors.append((n,loss))

#         #raise NotImplementError( 'how to early stop?' )

#     plt.plot(*zip(*incre_errors))
#     return incre_errors

# ======GridSearchCV=====
# def lnloss(lnp_y, lnp_yhat): # lnp_y=ln(y+1)
#     return utils.loss( np.expm1(lnp_y),  np.expm1(lnp_yhat) )
# losser = sklearn.metrics.make_scorer(lnloss,greater_is_better=False)
# folds=sklearn_ext.TimeSeriesCVSplit(Xdf.index.get_level_values('Date'),n_folds,vali_len,step)
# m = ExtraTreesRegressor()
# models = GridSearchCV(m,param_grid, cv=folds, n_jobs=1, scoring=losser,verbose=1) #refit=..., iid=... , pre_dispatch=...,
# models.fit(Xdf, ydf)
# print(models.best_score_)
# print(models.best_params_)

# XGB沒辦法early stopping with sklearn SearchCV因為validation set沒辦法傳給他xgb.fit(eval_set=[Xv,yv]), 雖然說應該改一下就好了
# gbm = xgb.XGBRegressor(**fix_params)
# models = GridSearchCV(gbm,param_grid, scoring=losser, cv=folds,
#                   fit_params={'early_stopping_rounds':5,'eval_set'=[(Xv,yv)],'eval_metric':utils.loss,},)
# #
