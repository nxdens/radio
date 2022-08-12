#!/usr/bin/env python
# coding=utf-8
"""
Based on LightningDataModule for managing data. A datamodule is a shareable,
reusable class that encapsulates all the steps needed to process data, i.e.,
decoupling datasets from models to allow building dataset-agnostic models. They
also allow you to share a full dataset without explaining how to download,
split, transform, and process the data.
"""

from abc import ABCMeta, abstractmethod
from typing import (Any, Mapping, Optional, Sequence, Sized, List, Tuple, cast,
                    Union)
from pathlib import Path
import shutil
from torch.utils.data import DataLoader, IterableDataset
import torchio as tio
import numpy as np
from ..settings.pathutils import is_dir_or_symlink, PathType
from .dataset import DatasetType
from .validation import TrainDataLoaderType, EvalDataLoaderType
from .basedatamodule import BaseDataModule
from .datatypes import TrainSizeType, EvalSizeType

__all__ = ["CerebroDataModule"]


class CerebroDataModule(BaseDataModule, metaclass=ABCMeta):
    """
    Base class For making Cerebro datasets which are compatible with
    torchvision.

    To create a subclass, you need to implement the following functions:

    A CerebroDataModule needs to implement 4 key methods + an optional
    __init__:

    <__init__>:
        (Optionally) Initialize the class, first call super.__init__().
    <get_subjects>:
        Key method, it should return a list of tio.Subjects.
    <default_preprocessing_transforms>:
        Default transforms to use in lieu of train_transforms, val_transforms,
        or test_transforms.
    <default_augmentation_transforms>:
        Default augmentation transforms to use during training if
        ``use_augmentation`` is ``True``.
    <teardown>:
        Things to do on every accelerator in distributed mode when finished.

    Typical Workflow
    ----------------
    data = CecrebroDataModule()
    data.prepare_data() # download
    data.setup(stage) # process and split
    data.teardown(stage) # clean-up

    Parameters
    ----------
    root : Path or str, optional
        Root to GPN's CEREBRO Studies folder.
        Default = ``'/media/cerebro/Studies'``.
    study : str, optional
        Study name. Default = ``''``.
    subj_dir : str, optional
        Subdirectory where the subjects are located.
        Default = ``'Public/data'``.
    data_dir : str, optional
        Subdirectory where the subjects' data are located.
        Default = ``''``.
    modalities : List[str], optional
        Which modalities to load. Default = ``[]``.
    labels : List[str], optional
        Which labels to load. Default = ``[]``.
    train_transforms : Callable, optional
        A function/transform that takes in a sample and returns a
        transformed version, e.g, ``torchvision.transforms.RandomCrop``.
    val_transforms : Callable, optional
        A function/transform that takes in a sample and returns a
        transformed version, e.g, ``torchvision.transforms.RandomCrop``.
    test_transforms : Callable, optional
        A function/transform that takes in a sample and returns a
        transformed version, e.g, ``torchvision.transforms.RandomCrop``.
    use_augmentation : bool, optional
        If ``True``, augment samples during the ``fit`` stage.
        Default = ``True``.
    use_preprocessing : bool, optional
        If ``True``, preprocess samples. Default = ``True``.
    resample : str, optional
        If an intensity name is provided, resample all images to specified
        intensity. Default = ``None``.
    batch_size : int, optional
        How many samples per batch to load. Default = ``32``.
    shuffle : bool, optional
        Whether to shuffle the data at every epoch. Default = ``False``.
    num_workers : int, optional
        How many subprocesses to use for data loading. ``0`` means that the
        data will be loaded in the main process. Default: ``0``.
    pin_memory : bool, optional
        If ``True``, the data loader will copy Tensors into CUDA pinned memory
        before returning them.
    drop_last : bool, optional
        Set to ``True`` to drop the last incomplete batch, if the dataset size
        is not divisible by the batch size. If ``False`` and the size of
        dataset is not divisible by the batch size, then the last batch will be
        smaller. Default = ``False``.
    num_folds : int, optional
        Number of folds. Must be at least ``2``. ``2`` corresponds to a single
        train/validation split. Default = ``2``.
    val_split: int or float, optional
        If ``num_folds = 2``, then ``val_split`` specify how the
        train_dataset should be split into train/validation datasets. If
        ``num_folds > 2``, then it is not used. Default = ``0.2``.
    dims : Tuple[int, int, int], optional
        Max spatial dimensions across subjects' images. If ``None``, compute
        dimensions from dataset. Default = ``(160, 192, 160)``.
    seed : int, optional
        When `shuffle` is True, `seed` affects the ordering of the indices,
        which controls the randomness of each fold. It is also use to seed the
        RNG used by RandomSampler to generate random indexes and
        multiprocessing to generate `base_seed` for workers. Pass an int for
        reproducible output across multiple function calls. Default = ``41``.
    verbose : bool, optional
        If ``True``, print debugging messages. Default = ``False``.
    """
    #: Dataset name
    name: str = ""
    #: Dataset class to use. E.g., torchvision.datasets.MNIST
    dataset_cls = tio.SubjectsDataset
    #: Extra arguments for dataset_cls instantiation.
    EXTRA_ARGS: dict = {}

    def __init__(
        self,
        *args: Any,
        root: PathType = Path('/media/cerebro/Studies'),
        study: str = '',
        subj_dir: str = 'Public/data',
        data_dir: str = '',
        modalities: Optional[List[str]] = None,
        labels: Optional[List[str]] = None,
        train_transforms: Optional[tio.Transform] = None,
        val_transforms: Optional[tio.Transform] = None,
        test_transforms: Optional[tio.Transform] = None,
        use_augmentation: bool = True,
        use_preprocessing: bool = True,
        resample: str = None,
        batch_size: int = 32,
        shuffle: bool = True,
        num_workers: int = 0,
        pin_memory: bool = True,
        drop_last: bool = False,
        num_folds: int = 2,
        val_split: Union[int, float] = 0.2,
        dims: Tuple[int, int, int] = (256, 256, 256),
        seed: int = 41,
        verbose: bool = False,
        **kwargs: Any,
    ) -> None:
        root = Path(root) / study / subj_dir
        super().__init__(
            *args,
            root=root,
            train_transforms=train_transforms,
            val_transforms=val_transforms,
            test_transforms=test_transforms,
            batch_size=batch_size,
            shuffle=shuffle,
            num_workers=num_workers,
            pin_memory=pin_memory,
            drop_last=drop_last,
            num_folds=num_folds,
            val_split=val_split,
            seed=seed,
            **kwargs,
        )
        self.study = study
        self.data_dir = data_dir
        self.subj_dir = subj_dir
        self.modalities = modalities if modalities else []
        self.labels = labels if labels else []
        resample_msg = "``resample`` must be a valid intensity name."
        if resample:
            assert resample in self.modalities, resample_msg
        self.resample = resample
        self.dims = dims
        self.use_augmentation = use_augmentation
        self.use_preprocessing = use_preprocessing
        self.verbose = verbose

    def check_if_data_split(self) -> None:
        """
        Check if data is splitted in train, test and val folders

        Parameters
        ----------
        data_dir: Optional[str]
            Subdirectory where the data is located. Default = ``""``.
        """
        has_train_folder = is_dir_or_symlink(self.root / self.data_dir /
                                             "train")
        has_test_folder = is_dir_or_symlink(self.root / self.data_dir / "test")
        has_val_folder = is_dir_or_symlink(self.root / self.data_dir / "val")
        self.has_train_test_split = bool(has_train_folder and has_test_folder)
        self.has_train_val_split = bool(has_train_folder and has_val_folder)

    def prepare_data(self, *args: Any, **kwargs: Any) -> None:
        """
        Verify data directory exists.
        Verify if test/train/val splitted.
        """
        if not is_dir_or_symlink(self.root):
            raise OSError('Study data directory not found!')
        self.check_if_data_split()

    def setup(self, stage: Optional[str] = None) -> None:
        """
        Creates train, validation and test collection of samplers.

        Parameters
        ----------
        stage: Optional[str]
            Either ``'fit``, ``'validate'``, or ``'test'``.
            If stage = ``None``, set-up all stages. Default = ``None``.
        """
        if stage in (None, "fit"):
            train_transforms = self.default_transforms(
                stage="fit"
            ) if self.train_transforms is None else self.train_transforms

            val_transforms = self.default_transforms(
                stage="fit"
            ) if self.val_transforms is None else self.val_transforms

            if not self.has_train_val_split:
                train_subjects = self.get_subjects(fold="train")
                train_dataset = self.dataset_cls(
                    train_subjects,
                    transform=train_transforms,
                    **self.EXTRA_ARGS,
                )
                val_dataset = self.dataset_cls(
                    train_subjects,
                    transform=val_transforms,
                    **self.EXTRA_ARGS,
                )
                self.validation = self.val_cls(
                    train_dataset=train_dataset,
                    val_dataset=val_dataset,
                    batch_size=self.batch_size,
                    shuffle=self.shuffle,
                    num_workers=self.num_workers,
                    pin_memory=self.pin_memory,
                    drop_last=self.drop_last,
                    num_folds=self.num_folds,
                    seed=self.seed,
                )
                self.validation.setup(self.val_split)
                self.has_validation = True
                self.train_dataset = train_dataset
                self.size_train = self.size_train_dataset(
                    self.validation.train_samplers)
                self.val_dataset = val_dataset
                self.size_val = self.size_eval_dataset(
                    self.validation.val_samplers)
            else:
                train_subjects = self.get_subjects(fold="train")
                self.train_dataset = self.dataset_cls(
                    train_subjects,
                    transform=train_transforms,
                    **self.EXTRA_ARGS,
                )
                self.size_train = self.size_train_dataset(self.train_dataset)

                val_subjects = self.get_subjects(fold="val")
                self.val_dataset = self.dataset_cls(
                    val_subjects,
                    transform=val_transforms,
                    **self.EXTRA_ARGS,
                )
                self.size_val = self.size_eval_dataset(self.val_dataset)

        if stage in (None, "test"):
            test_transforms = self.default_transforms(
                stage="test"
            ) if self.test_transforms is None else self.test_transforms
            test_subjects = self.get_subjects(fold="test")
            self.test_dataset = self.dataset_cls(
                test_subjects,
                transform=test_transforms,
                **self.EXTRA_ARGS,
            )
            self.size_test = self.size_eval_dataset(self.test_dataset)

    @abstractmethod
    def get_subjects(self, fold: str = "train") -> List[tio.Subject]:
        """
        Get train, test, or val list of TorchIO Subjects.

        Parameters
        ----------
        fold : str, optional
            Identify which type of dataset, ``'train'``, ``'test'``, or
            ``'val'``. Default = ``'train'``.

        Returns
        -------
        _ : List[tio.Subject]
            Train, test or val list of TorchIO Subjects.
        """

    def default_transforms(
        self,
        stage: Optional[str] = None,
    ) -> tio.Transform:
        """
        Default transforms and augmentations for the dataset.

        Parameters
        ----------
        stage: Optional[str]
            Either ``'fit``, ``'validate'``, ``'test'``, or ``'predict'``.
            If stage = None, set-up all stages. Default = None.

        Returns
        -------
        _: tio.Transform
            All preprocessing steps (and if ``'fit'``, augmentation steps too)
            that should be applied to the subjects.
        """
        transforms: List[tio.transforms.Transform] = []
        if self.use_preprocessing:
            preprocess = self.get_preprocessing_transforms(
                shape=self.dims,
                resample=self.resample,
            )
            transforms.append(preprocess)
        if stage in (None, "fit") and self.use_augmentation:
            augment = self.get_augmentation_transforms()
            transforms.append(augment)

        return tio.Compose(transforms)

    def get_preprocessing_transforms(
        self,
        shape: Optional[Tuple[int, int, int]] = None,
        resample: str = None,
    ) -> tio.Transform:
        """
        Get preprocessing transorms to apply to all subjects.

        Returns
        -------
        preprocess : tio.Transform
            All preprocessing steps that should be applied to all subjects.
        """
        preprocess_list: List[tio.Transform] = []

        # Use standard orientation for all images, RAS+
        preprocess_list.append(tio.ToCanonical())

        if resample:
            preprocess_list.append(tio.Resample(resample))

        if shape is None:
            train_subjects = self.get_subjects(fold="train")
            val_subjects = self.get_subjects(fold="val")
            test_subjects = self.get_subjects(fold="test")
            shape = self.get_max_shape(train_subjects + val_subjects +
                                       test_subjects)
        else:
            shape = self.dims

        preprocess_list.extend(
            self.default_preprocessing_transforms(shape=shape))

        return tio.Compose(preprocess_list)

    @abstractmethod
    def default_preprocessing_transforms(self,
                                         **kwargs: Any) -> List[tio.Transform]:
        """
        List with preprocessing transforms to apply to all subjects.

        Returns
        -------
        preprocess : List[tio.Transform]
            Preprocessing transforms that should be applied to all subjects.

        Examples
        --------
        shape = kwargs.get("shape", (256, 256, 256))
        return [
            tio.RescaleIntensity((-1, 1)),
            tio.CropOrPad(shape),
            tio.EnsureShapeMultiple(8),  # better suited for U-Net type Nets
            tio.OneHot()  # for labels
        ]
        """

    def get_augmentation_transforms(self) -> tio.Transform:
        """"
        Get augmentation transorms to apply to subjects during training.

        Returns
        -------
        augment : tio.Transform
            All augmentation steps that should be applied to subjects during
            training.
        """
        augment = tio.Compose(self.default_augmentation_transforms())
        return augment

    @abstractmethod
    def default_augmentation_transforms(self,
                                        **kwargs: Any) -> List[tio.Transform]:
        """
        List with augmentation transforms to apply to training subjects.

        Returns
        -------
        _ : List[tio.Transform]
            Augmentation transforms to apply to training subjects.

        Examples
        --------
        random_gamma_p = kwargs.get("random_gamma_p", 0.5)
        random_noise_p = kwargs.get("random_noise_p", 0.5)
        random_motion_p = kwargs.get("random_motion_p", 0.1)
        random_bias_field_p = kwargs.get("random_bias_field_p", 0.25)
        return [
            tio.RandomAffine(),
            tio.RandomGamma(p=random_gamma_p),
            tio.RandomNoise(p=random_noise_p),
            tio.RandomMotion(p=random_motion_p),
            tio.RandomBiasField(p=random_bias_field_p),
        ]
        """

    @staticmethod
    def get_max_shape(subjects: List[tio.Subject]) -> Tuple[int, int, int]:
        """
        Get max height, width, and depth accross all subjects.

        Parameters
        ----------
        subjects : List[tio.Subject]
            List of TorchIO Subject objects.

        Returns
        -------
        shapes_tuple : Tuple[int, int, int]
            Max height, width and depth across all subjects.
        """
        dataset = tio.SubjectsDataset(subjects)
        shapes = np.array([
            image.spatial_shape for subject in dataset.dry_iter()
            for image in subject.get_images()
        ])

        shapes_tuple = tuple(map(int, shapes.max(axis=0).tolist()))
        return cast(Tuple[int, int, int], shapes_tuple)

    @staticmethod
    def size_train_dataset(train_dataset: Sized) -> TrainSizeType:
        """
        Compute the size of the train datasets.

        Parameters
        ----------
        train_dataset: TrainDatasetType
            Collection of train datasets.

        Returns
        -------
        _ : TrainSizeType
            Collection of train datasets' sizes.
        """

        def _handle_is_mapping(dataset):
            mapping = {}
            for key, dset in dataset.items():
                if isinstance(dset, Mapping):
                    mapping[key] = _handle_is_mapping(dset)
                if isinstance(dset, Sequence):
                    mapping[key] = _handle_is_sequence(dset)
                mapping[key] = len(dset)
            return mapping

        def _handle_is_sequence(dataset):
            sequence = []
            for dset in dataset:
                if isinstance(dset, Mapping):
                    sequence.append(_handle_is_mapping(dset))
                if isinstance(dset, Sequence):
                    sequence.append(_handle_is_sequence(dset))
                sequence.append(len(dset))
            return sequence

        if isinstance(train_dataset, Mapping):
            return _handle_is_mapping(train_dataset)
        if isinstance(train_dataset, Sequence):
            if len(train_dataset) == 1:
                return CerebroDataModule.size_train_dataset(train_dataset[0])
            return _handle_is_sequence(train_dataset)
        return len(train_dataset)

    @staticmethod
    def size_eval_dataset(eval_dataset: Sized) -> EvalSizeType:
        """
        Compute the size of the test or validation datasets.

        Parameters
        ----------
        eval_dataset: EvalDatasetType
            Collection of test or validation datasets.

        Returns
        -------
        _ : EvalSizeType
            Collection of test or validation datasets' sizes.
        """
        if isinstance(eval_dataset, Sequence):
            if len(eval_dataset) == 1:
                return len(eval_dataset[0])
            return [len(ds) for ds in eval_dataset]
        return len(eval_dataset)

    def dataloader(
        self,
        dataset: DatasetType,
        batch_size: Optional[int] = None,
        shuffle: Optional[bool] = None,
        num_workers: Optional[int] = None,
        pin_memory: Optional[bool] = None,
        drop_last: Optional[bool] = None,
    ) -> DataLoader:
        """
        Instantiate a DataLoader.

        Parameters
        ----------
        batch_size : int, optional
            How many samples per batch to load. Default = ``32``.
        shuffle : bool, optional
            Whether to shuffle the data at every epoch. Default = ``False``.
        num_workers : int, optional
            How many subprocesses to use for data loading. ``0`` means that the
            data will be loaded in the main process. Default: ``0``.
        pin_memory : bool, optional
            If ``True``, the data loader will copy Tensors into CUDA pinned
            memory before returning them.
        drop_last : bool, optional
            Set to ``True`` to drop the last incomplete batch, if the dataset
            size is not divisible by the batch size. If ``False`` and the size
            of dataset is not divisible by the batch size, then the last batch
            will be smaller. Default = ``False``.

        Returns
        -------
        _ : DataLoader
        """
        shuffle = shuffle if shuffle else self.shuffle
        shuffle &= not isinstance(dataset, IterableDataset)
        return DataLoader(
            dataset=dataset,
            batch_size=batch_size if batch_size else self.batch_size,
            shuffle=shuffle,
            num_workers=num_workers if num_workers else self.num_workers,
            pin_memory=pin_memory if pin_memory else self.pin_memory,
            drop_last=drop_last if drop_last else self.drop_last,
        )

    def train_dataloader(self, *args: Any,
                         **kwargs: Any) -> TrainDataLoaderType:
        """
        Generates one or multiple Pytorch DataLoaders for train.

        Returns
        -------
        _ : Collection of DataLoader
            Collection of train dataloaders specifying training samples.
        """
        loader_kwargs = {}
        loader_kwargs["batch_size"] = kwargs.get("batch_size", None)
        loader_kwargs["shuffle"] = kwargs.get("shuffle", None)
        loader_kwargs["num_workers"] = kwargs.get("num_workers", None)
        loader_kwargs["pin_memory"] = kwargs.get("pin_memory", None)
        loader_kwargs["drop_last"] = kwargs.get("drop_last", None)

        def _handle_is_mapping(dataset):
            mapping = {}
            for key, dset in dataset.items():
                if isinstance(dset, Mapping):
                    mapping[key] = _handle_is_mapping(dset)
                if isinstance(dset, Sequence):
                    mapping[key] = _handle_is_sequence(dset)
                mapping[key] = self.dataloader(dset, **loader_kwargs)
            return mapping

        def _handle_is_sequence(dataset):
            sequence = []
            for dset in dataset:
                if isinstance(dset, Mapping):
                    sequence.append(_handle_is_mapping(dset))
                if isinstance(dset, Sequence):
                    sequence.append(_handle_is_sequence(dset))
                sequence.append(self.dataloader(dset, **loader_kwargs))
            return sequence

        if self.has_validation:
            return self.validation.train_dataloader()

        if isinstance(self.train_dataset, Mapping):
            return _handle_is_mapping(self.train_dataset)
        if isinstance(self.train_dataset, Sequence):
            if len(self.train_dataset) == 1:
                if isinstance(self.train_dataset[0], Mapping):
                    return _handle_is_mapping(self.train_dataset[0])
                if isinstance(self.train_dataset[0], Sequence):
                    if len(self.train_dataset[0]) == 1:
                        return self.dataloader(self.train_dataset[0][0],
                                               **loader_kwargs)
                    return _handle_is_sequence(self.train_dataset[0])
                return self.dataloader(self.train_dataset[0], **loader_kwargs)
            return _handle_is_sequence(self.train_dataset)
        return self.dataloader(self.train_dataset, **loader_kwargs)

    def val_dataloader(self, *args: Any, **kwargs: Any) -> EvalDataLoaderType:
        """
        Generates one or multiple Pytorch DataLoaders for validation.

        Returns
        -------
        _ : Collection of DataLoader
            Collection of validation dataloaders specifying validation samples.
        """
        if self.has_validation:
            return self.validation.val_dataloader()

        loader_kwargs = {}
        loader_kwargs["batch_size"] = kwargs.get("batch_size", None)
        loader_kwargs["shuffle"] = kwargs.get("shuffle", None)
        loader_kwargs["num_workers"] = kwargs.get("num_workers", None)
        loader_kwargs["pin_memory"] = kwargs.get("pin_memory", None)
        loader_kwargs["drop_last"] = kwargs.get("drop_last", None)

        if isinstance(self.val_dataset, Sequence):
            if len(self.val_dataset) == 1:
                return self.dataloader(self.val_dataset[0], **loader_kwargs)
            return [
                self.dataloader(ds, **loader_kwargs) for ds in self.val_dataset
            ]
        return self.dataloader(self.val_dataset, **loader_kwargs)

    def test_dataloader(self, *args: Any, **kwargs: Any) -> EvalDataLoaderType:
        """
        Generates one or multiple Pytorch DataLoaders for test.

        Returns
        -------
        _ : Collection of DataLoaders
            Collection of test dataloaders specifying test samples.
        """
        loader_kwargs = {}
        loader_kwargs["batch_size"] = kwargs.get("batch_size", None)
        loader_kwargs["shuffle"] = kwargs.get("shuffle", None)
        loader_kwargs["num_workers"] = kwargs.get("num_workers", None)
        loader_kwargs["pin_memory"] = kwargs.get("pin_memory", None)
        loader_kwargs["drop_last"] = kwargs.get("drop_last", None)

        if isinstance(self.test_dataset, Sequence):
            if len(self.test_dataset) == 1:
                return self.dataloader(self.test_dataset[0], **loader_kwargs)
            return [
                self.dataloader(ds, **loader_kwargs)
                for ds in self.test_dataset
            ]
        return self.dataloader(self.test_dataset, **loader_kwargs)

    def predict_dataloader(self, *args: Any,
                           **kwargs: Any) -> EvalDataLoaderType:
        pass

    def teardown(self, stage: Optional[str] = None) -> None:
        """
        Called at the end of fit (train + validate), validate, test,
        or predict. Remove root directory if a temporary was used.

        Parameters
        ----------
        stage: Optional[str]
            Either ``'fit``, ``'validate'``, or ``'test'``.
            If stage = None, set-up all stages. Default = None.
        """
        if self.is_temp_dir:
            shutil.rmtree(self.root)
