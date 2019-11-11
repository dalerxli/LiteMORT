import pandas as pd
import numpy as np
import gc
from ctypes import *
from pandas.api.types import is_string_dtype
from pandas.api.types import is_numeric_dtype
import random

class M_COLUMN(Structure):
    _fields_ = [    ('name',c_char_p),
                    ('data',c_void_p),
                    ('dtype', c_char_p),
                    ('type_x', c_char_p),
                    ('v_min', c_double),
                    ('v_max', c_double),
                    ('representive', c_float),
               ]

class M_DATASET(Structure):
    _fields_ = [    ('name',c_char_p),
                    ('nSamp', c_int64),
                    ('ldFeat',c_int),
                    ('ldY', c_int),
                    ('columnX', POINTER(M_COLUMN)),
                    ('columnY', POINTER(M_COLUMN)),
                    ('merge_left', POINTER(M_COLUMN)),
                    ('merge_right', c_int),
                    ('x', c_int),
                    ]

    def __init__(self, name_, nSamp_,nFeat,nY):
        self.name = str(name_).encode('utf8')
        self.nSamp = nSamp_
        self.ldFeat = nFeat
        self.ldY = nY
        self.columnX=None;          self.columnY = None
        self.merge_left=None;       self.merge_right=-1

class M_DATASET_LIST(Structure):
    _fields_ = [    ('name',c_char_p),
                    ('nSet', c_int),
                    ('list', POINTER(M_DATASET)),
                    ('flag', c_int)
               ]

    def __init__(self, name_, datasets,flag=0):
        assert(len(datasets)>0)
        self.name = str(name_).encode('utf8')
        self.nSet = len(datasets)
        self.list = (M_DATASET * self.nSet)(*datasets)
        self.flag = flag

def Mort_PickSamples(pick_samples,df_train,df_test):
    nTrain = df_train.shape[0]
    random.seed(42)
    subset = random.sample(range(nTrain), pick_samples)
    df_train = df_train.iloc[subset, :].reset_index(drop=True)
    print('====== Mort_PickSamples ... df_train={}'.format(df_train.shape))
    if df_test is not None:
        nTest =df_test.shape[0]
        subset = random.sample(range(nTest), pick_samples)
        df_test = df_test.iloc[subset, :].reset_index(drop=True)
        print('====== Mort_PickSamples ... df_test={}'.format(df_test.shape))
    return df_train,df_test

class Mort_Preprocess(object):
    def column_info(self,feat,X,categorical_feature=None,discrete_feature=None):
        col = M_COLUMN()
        col.name = str(feat).encode('utf8')
        col.data = None
        col.dtype = None
        col.representive = np.float32(0)
        x_info,type_x = '',''
        if isinstance(X, pd.DataFrame):
            narr = None
            isCat =(categorical_feature is not None) and (feat in categorical_feature)
            dtype = X[feat].dtype
            if isCat or dtype.name == 'category':
                x_info = 'category'
                type_x = '*'
            isDiscrete = (discrete_feature is not None) and (feat in discrete_feature)
            if isDiscrete:
                x_info = 'discrete'
                type_x = '#'
            if X[feat].dtype.name == 'category':
                narr = X[feat].cat.codes.values
            elif is_numeric_dtype(X[feat]):
                narr = X[feat].values
            else:
                pass
        elif isinstance(X, pd.Series):
            type_x='S'
            x_info = 'Series'
            narr = X.values
        elif isinstance(X, np.ndarray):
            narr = X
        else:
            pass
        if narr is not None:
            col.type_x=str(type_x).encode('utf8')
            col.v_min=narr.min();      col.v_max=narr.max()
            col.data = narr.ctypes.data_as(c_void_p)
            col.dtype = str(narr.dtype).encode('utf8')
            #print("\"{}\":\t{}\ttype={},data={},name={}".format(feat, x_info, col.dtype, col.data, col.name))
        return col

    def OnMerge(self,df_base,merge_infos):
        nFV=len(merge_infos)
        self.df_merge = pd.DataFrame()#pd.DataFrame(0, index=np.arange(self.nSample), columns=feature_list)
        feature_list=[]
        merge_left=[]
        for i in range(nFV):
            info = merge_infos[i]
            df,cols_on = info['dataset'],info['on']
            feature_list.append("merge_"+info['desc'])

            df_left, df_rigt = df_base[cols_on], df[cols_on]
            df_left_0 = df_left.reset_index()
            df_rigt["row_no"] = df_rigt.reset_index().index
            dtype = np.int32
            if False:  # mapping  吃力不讨好
                mapping = df_map.set_index(cols_on).T.to_dict('list')  # set.set_index('ID').T.to_dict('list')
            else:
                df_left = df_left.merge(df_rigt, on=cols_on, how='left')
                self.df_merge[feature_list[i]]=df_left["row_no"]
                nNA = self.df_merge[feature_list[i]].isna().sum()
                if(nNA>0):      #真麻烦！！！
                    print(f"OnMerge STRANGE@{cols_on}\tnNA={nNA}/{nNA*100.0/self.nSample:.3g}%%")
                    #self.df_merge[feature_list[i]]=self.df_merge[feature_list[i]].astype('Int64')
                else:
                    self.df_merge[feature_list[i]]=self.df_merge[feature_list[i]].astype(np.int32)
                del df_left,df_rigt
                gc.collect()
            col = self.column_info(feature_list[i], self.df_merge, self.categorical_feature, self.discrete_feature)
            merge_left.append(col)
        self.cpp_dat_.merge_left = (M_COLUMN * len(merge_left))(*merge_left)

    def __init__(self,name_,X,y,params,features=None,feat_info=None,merge_infos=None,  **kwargs):
    #v0.2   需要配置更多的信息
    #def __init__(self, name_, X, y, params, features_infos=None,**kwargs):
        '''
        :param X:
        :param y:
        :param features:
        :param categorical_feature:
        :param kwargs:
        '''

        if not (isinstance(X, pd.DataFrame) or isinstance(X, np.ndarray)):
            raise NotImplementedError("Mort_Preprocess failed to init @{}".format(X))
        self.name = name_
        self.nSample,self.nFeature = X.shape[0],X.shape[1]
        self.categorical_feature=feat_info['categorical'] if feat_info is not None and 'categorical' in feat_info else None
        self.discrete_feature = feat_info['discrete'] if feat_info is not None and 'discrete' in feat_info else None
        self.col_X,self.col_Y=[],[]
        if features is None:
            if isinstance(X, pd.DataFrame):
                self.features = X.columns
            else:
                pass
        else:
            self.features = features

        for feat in self.features:
            col = self.column_info(feat,X,self.categorical_feature,self.discrete_feature)
            if 'representive' in params.__dict__ and feat in params.representive:
                col.representive = params.representive[feat]
            if col.data is not None:
                self.col_X.append(col)
        if y is not None:
            col=self.column_info('target',y,self.categorical_feature,self.discrete_feature)
            if col.data is None:
                raise( "Mort_Preprocess: col_Y is NONE!!! " )
            self.col_Y=[col]
        cpp_dat_ = M_DATASET(self.name,self.nSample,len(self.col_X),len(self.col_Y))
        cpp_dat_.columnX = (M_COLUMN * len(self.col_X))(*self.col_X)
        cpp_dat_.columnY = (M_COLUMN * len(self.col_Y))(*self.col_Y)
        self.cpp_dat_ = cpp_dat_

        if merge_infos is not None:
            self.OnMerge(X,merge_infos)
        return    #please implement this

    def OrdinalEncode_(X,X_test,features=None):
        encoding_dict = dict()
        if features is None:
            features = X.columns
        for col in features:
            values = X[col].value_counts().index.tolist()
            # create a dictionary of values and corresponding number {value, number}
            dict_values = {value: count for value, count in zip(values, range(1, len(values) + 1))}
            # save the values to encode in the dictionary
            encoding_dict[col] = dict_values
            # replace the values with the corresponding number from the dictionary
            X[col] = X[col].map(lambda x: dict_values.get(x))
            X_test[col] = X_test[col].map(lambda x: dict_values.get(x))
        gc.collect()
        return X,X_test

    def fit(self,):
        """
        需要精心设计诶     Each entry in that list must be either 'numerical' or 'categorical'
        """
        pass  # please implement this

    def transform(self,):
        """
        Each entry in that list must be either 'numerical' or 'categorical'
        """
        pass