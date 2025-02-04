#!/usr/bin/env python
# coding=utf-8
"""
Based on BaseDataModule for managing data. A vision datamodule that is
shareable, reusable class that encapsulates all the steps needed to process
data, i.e., decoupling datasets from models to allow building dataset-agnostic
models. They also allow you to share a full dataset without explaining how to
download, split, transform, and process the data.
"""

from typing import Any, Dict, List, Optional, Tuple, Union, cast
from pathlib import Path
from string import Template
import torchio as tio  # type: ignore
import numpy as np
from torch.utils.data import DataLoader
from radio.settings.pathutils import PathType, ensure_exists
from ..datatypes import SpatialShapeType
from ..datautils import create_probability_map, get_subjects_from_batch
from ..datavisualization import rotate, import_mpl_plt
from .hcp import HCPDataModule

__all__ = ["HCPPatchDataModule"]


class HCPPatchDataModule(HCPDataModule):
    """
    class por making patch-based datasets which are compatible with
    torchvision from the Human Connectome Project Data.

    Typical Workflow
    ----------------
    data = HCPPatchDataModule()
    data.prepare_data() # download
    data.setup(stage) # process and split
    data.teardown(stage) # clean-up

    Parameters
    ----------
    root : Path or str, optional
        Root to data root folder.
        Default = ``'/data'``.
    study : str, optional
        Study name. Default = ``'HCP'``.
    subj_dir : str, optional
        Subdirectory where the subjects are located.
        Default = ``''``.
    data_dir : str, optional
        Subdirectory where the subjects' data arkk located.
        Default = ``'unprocessed'``.
    patch_size : int or (int, int, int)
        Tuple of integers ``(w, h, d)`` to generate patches of size ``w x h x
        d``. If a single number ``n`` is provided, ``w = h = d = n``.
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
    resample : bool, optional
        If ``True``, resample all images to ``'T1'``. Default = ``False``.
    probability_map : str, optional
        Name of the image in the input subject that will be used as a sampling
        probability map.  The probability of sampling a patch centered on a
        specific voxel is the value of that voxel in the probability map. The
        probabilities need not be normalized. For example, voxels can have
        values 0, 1 and 5. Voxels with value 0 will never be at the center of a
        patch. Voxels with value 5 will have 5 times more chance of being at
        the center of a patch that voxels with a value of 1. If ``None``,
        uniform sampling is used. Default = ``None``.
    label_name : str, optional
        Name of the label image in the subject that will be used to generate
        the sampling probability map. If ``None`` and ``probability_map`` is
        ``None``, the first image of type ``torchio.LABEL`` found in the
        subject subject will be used. If ``probability_map`` is not ``None``,
        then ``label_name`` and ``label_probability`` are ignored.
        Default = ``None``.
    label_probabilities : Dict[int, float], optional
        Dictionary containing the probability that each class will be sampled.
        Probabilities do not need to be normalized. For example, a value of
        {0: 0, 1: 2, 2: 1, 3: 1} will create a sampler whose patches centers
        will have 50% probability of being labeled as 1, 25% of being 2 and 25%
        of being 3. If None, the label map is binarized and the value is set to
        {0: 0, 1: 1}. If the input has multiple channels, a value of
        {0: 0, 1: 2, 2: 1, 3: 1} will create a sampler whose patches centers
        will have 50% probability of being taken from a non zero value of
        channel 1, 25% from channel 2 and 25% from channel 3. If
        ``probability_map`` is not ``None``, then ``label_name`` and
        ``label_probability`` are ignored. Default = ``None``.
    queue_max_length : int, optional
        Maximum number of patches that can be stored in the queue. Using a
        large number means that the queue needs to be filled less often, but
        more CPU memory is needed to store the patches. Default = ``256``.
    samples_per_volume : int, optional
        Number of patches to extract from each volume. A small number of
        patches ensures a large variability in the queue, but training will be
        slower. Default = ``16``.
    batch_size : int, optional
        How many patches per batch to load. Default = ``32``.
    shuffle_subjects : bool, optional
        Whether to shuffle the subjects dataset at the beginning of every epoch
        (an epoch ends when all the patches from all the subjects have been
        processed). Default = ``True``.
    shuffle_patches : bool, optional
        Whether to shuffle the patches queue at the beginning of every epoch.
        Default = ``True``.
    num_workers : int, optional
        How many subprocesses to use for data loading. ``0`` means that the
        data will be loaded in the main process. Default: ``0``.
    pin_memory : bool, optional
        If ``True``, the data loader will copy Tensors into CUDA pinned memory
        before returning them.
    start_background : bool, optional
        If ``True``, the loader will start working in the background as soon as
        the queues are instantiated. Default = ``True``.
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
    modalities : List[str], optional
        Which modalities to load. Default = ``['3T_MPR']``.
    labels : List[str], optional
        Which labels to load. Default = ``[]``.
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
    #: Extra arguments for dataset_cls instantiation.
    EXTRA_ARGS: dict = {}
    #: Dataset name
    name: str = "HCP_patch"
    #: Dataset class to use. E.g., torchvision.datasets.MNIST
    dataset_cls = tio.SubjectsDataset
    img_template = Template(
        '${modality}/${subj_id}_${field}_${modality}.nii.gz')
    img_template_radio = Template('${subj_id}_-_${field}_-_${modality}.nii.gz')
    png_template_radio = Template('${subj_id}_-_${field}_-_${modality}.png')
    label_template: Template = Template("")
    label_template_radio: Template = Template("")

    def __init__(
        self,
        *args: Any,
        root: PathType = Path('/data'),
        study: str = 'HCP',
        subj_dir: str = '',
        data_dir: str = 'unprocessed',
        train_transforms: Optional[tio.Transform] = None,
        val_transforms: Optional[tio.Transform] = None,
        test_transforms: Optional[tio.Transform] = None,
        use_augmentation: bool = True,
        use_preprocessing: bool = True,
        resample: bool = False,
        patch_size: SpatialShapeType = 96,
        probability_map: Optional[str] = None,
        create_custom_probability_map: bool = False,
        label_name: Optional[str] = None,
        label_probabilities: Optional[Dict[int, float]] = None,
        queue_max_length: int = 256,
        samples_per_volume: int = 16,
        batch_size: int = 32,
        shuffle_subjects: bool = True,
        shuffle_patches: bool = True,
        num_workers: int = 0,
        pin_memory: bool = True,
        start_background: bool = True,
        drop_last: bool = False,
        num_folds: int = 2,
        val_split: Union[int, float] = 0.2,
        modalities: Optional[List[str]] = None,
        labels: Optional[List[str]] = None,
        dims: Tuple[int, int, int] = (256, 320, 320),
        seed: int = 41,
        verbose: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            *args,
            root=root,
            study=study,
            subj_dir=subj_dir,
            data_dir=data_dir,
            train_transforms=train_transforms,
            val_transforms=val_transforms,
            test_transforms=test_transforms,
            use_augmentation=use_augmentation,
            use_preprocessing=use_preprocessing,
            resample=resample,
            batch_size=batch_size,
            shuffle=shuffle_subjects,
            num_workers=num_workers,
            pin_memory=pin_memory,
            drop_last=drop_last,
            num_folds=num_folds,
            val_split=val_split,
            modalities=modalities,
            labels=labels,
            dims=dims,
            seed=seed,
            verbose=verbose,
            **kwargs,
        )
        self.train_sampler: tio.data.sampler.sampler.PatchSampler

        if create_custom_probability_map:
            probability_map = 'sampling_map'

        # Init Train Sampler
        both_something = probability_map is not None and label_name is not None
        if both_something:
            raise ValueError(
                "Both 'probability_map' and 'label_name' cannot be not None ",
                "at the same time",
            )
        if probability_map is None and label_name is None:
            self.train_sampler = tio.UniformSampler(patch_size)
        elif probability_map is not None:
            self.train_sampler = tio.WeightedSampler(patch_size,
                                                     probability_map)
        else:
            self.train_sampler = tio.LabelSampler(patch_size, label_name,
                                                  label_probabilities)

        self.probability_map = probability_map
        self.create_custom_probability_map = create_custom_probability_map
        self.patch_size = patch_size
        self.label_name = label_name
        self.label_probabilities = label_probabilities

        # Queue parameters
        self.train_queue: tio.Queue
        self.val_queue: tio.Queue
        self.queue_max_length = queue_max_length
        self.samples_per_volume = samples_per_volume
        self.shuffle_subjects = shuffle_subjects
        self.shuffle_patches = shuffle_patches
        self.start_background = start_background

    def setup(self, stage: Optional[str] = None) -> None:
        """
        Creates train, validation and test collection of samplers.

        Parameters
        ----------
        stage: Optional[str]
            Either ``'fit``, ``'validate'``, or ``'test'``.
            If stage = ``None``, set-up all stages. Default = ``None``.
        """
        if stage == "fit" or stage is None:
            train_transforms = self.default_transforms(
                stage="fit"
            ) if self.train_transforms is None else self.train_transforms

            val_transforms = self.default_transforms(
                stage="fit"
            ) if self.val_transforms is None else self.val_transforms

            if not self.has_train_val_split:
                train_subjects = self.get_subjects(fold="train")
                if self.create_custom_probability_map:
                    train_subjects = self.add_sampling_map(train_subjects)
                train_dataset = self.dataset_cls(
                    train_subjects,
                    transform=train_transforms,
                )
                val_dataset = self.dataset_cls(
                    train_subjects,
                    transform=val_transforms,
                )
                self.train_queue = tio.Queue(
                    cast(tio.SubjectsDataset, train_dataset),
                    max_length=self.queue_max_length,
                    samples_per_volume=self.samples_per_volume,
                    sampler=self.train_sampler,
                    num_workers=self.num_workers,
                    shuffle_subjects=self.shuffle_subjects,
                    shuffle_patches=self.shuffle_patches,
                    start_background=self.start_background,
                    verbose=self.verbose)

                self.val_queue = tio.Queue(
                    cast(tio.SubjectsDataset, val_dataset),
                    max_length=self.queue_max_length,
                    samples_per_volume=self.samples_per_volume,
                    sampler=self.train_sampler,
                    num_workers=self.num_workers,
                    shuffle_subjects=self.shuffle_subjects,
                    shuffle_patches=self.shuffle_patches,
                    start_background=self.start_background,
                    verbose=self.verbose)

                self.validation = self.val_cls(
                    train_dataset=self.train_queue,
                    val_dataset=self.val_queue,
                    batch_size=self.batch_size,
                    shuffle=False,
                    num_workers=0,
                    pin_memory=self.pin_memory,
                    drop_last=self.drop_last,
                    num_folds=self.num_folds,
                    seed=self.seed,
                )
                self.validation.setup(self.val_split)
                self.has_validation = True
                self.train_dataset = self.train_queue
                self.size_train = self.size_train_dataset(
                    self.validation.train_samplers)
                self.val_dataset = self.val_queue
                self.size_val = self.size_eval_dataset(
                    self.validation.val_samplers)
            else:
                train_subjects = self.get_subjects(fold="train")
                if self.create_custom_probability_map:
                    train_subjects = self.add_sampling_map(train_subjects)
                train_dataset = self.dataset_cls(train_subjects,
                                                 transform=train_transforms)
                self.train_queue = tio.Queue(
                    cast(tio.SubjectsDataset, train_dataset),
                    max_length=self.queue_max_length,
                    samples_per_volume=self.samples_per_volume,
                    sampler=self.train_sampler,
                    num_workers=self.num_workers,
                    shuffle_subjects=self.shuffle_subjects,
                    shuffle_patches=self.shuffle_patches,
                    start_background=self.start_background,
                    verbose=self.verbose)

                val_subjects = self.get_subjects(fold="val")
                if self.create_custom_probability_map:
                    train_subjects = self.add_sampling_map(val_subjects)
                val_dataset = self.dataset_cls(val_subjects,
                                               transform=val_transforms)
                self.train_dataset = self.train_queue
                self.size_train = self.size_train_dataset(self.train_dataset)

                self.val_queue = tio.Queue(
                    cast(tio.SubjectsDataset, val_dataset),
                    max_length=self.queue_max_length,
                    samples_per_volume=self.samples_per_volume,
                    sampler=self.train_sampler,
                    num_workers=self.num_workers,
                    shuffle_subjects=self.shuffle_subjects,
                    shuffle_patches=self.shuffle_patches,
                    start_background=self.start_background,
                    verbose=self.verbose)
                self.val_dataset = self.val_queue
                self.size_val = self.size_eval_dataset(self.val_dataset)

        if stage == "test" or stage is None:
            test_transforms = self.default_transforms(
                stage="test"
            ) if self.test_transforms is None else self.test_transforms
            test_subjects = self.get_subjects(fold="test")
            self.test_dataset = self.dataset_cls(test_subjects,
                                                 transform=test_transforms)
            self.size_test = self.size_eval_dataset(self.test_dataset)

    def get_preprocessing_transforms(
        self,
        shape: Optional[Tuple[int, int, int]] = None,
        resample: bool = False,
        resample_reference: str = '3T_MPR',
    ) -> tio.Transform:
        """
        Get preprocessing transorms to apply to all subjects.

        Parameters
        ----------
        shape : Tuple[int, int, int], Optional
            A tuple with the shape for the CropOrPad transform.
            Default = ``None``.
        resample : bool, Optional
            If True, resample to ``resample_reference``. Default = ``False``.
        resample_reference : str, Optional
            Name of the image to resample to. Default = ``"3T_MPR"```.

        Returns
        -------
        preprocess : tio.Transform
            All preprocessing steps that should be applied to all subjects.
        """
        preprocess_list: List[tio.transforms.Transform] = []

        # Use standard orientation for all images
        preprocess_list.append(tio.ToCanonical())

        # If true, resample to ``resample_reference``
        if resample:
            preprocess_list.append(tio.Resample(resample_reference))

        if shape is None:
            train_subjects = self.get_subjects(fold="train")
            test_subjects = self.get_subjects(fold="test")
            val_subjects = self.get_subjects(fold="val")
            shape = self.get_max_shape(train_subjects + test_subjects +
                                       val_subjects)
        else:
            shape = self.dims

        preprocess_list.extend([
            tio.RescaleIntensity((-1, 1)),
            # tio.ZNormalization(masking_method=lambda x: x > x.mean()),
            # tio.ZNormalization(),
            tio.CropOrPad(shape),
            tio.EnsureShapeMultiple(8),  # for the U-Net
            tio.OneHot()
        ])

        return tio.Compose(preprocess_list)

    @staticmethod
    def get_augmentation_transforms() -> tio.Transform:
        """"
        Get augmentation transorms to apply to subjects during training.

        Returns
        -------
        augment : tio.Transform
            All augmentation steps that should be applied to subjects during
            training.
        """
        augment = tio.Compose([
            tio.RandomAffine(),
            tio.RandomGamma(p=0.5),
            tio.RandomNoise(p=0.5),
            tio.RandomMotion(p=0.1),
            tio.RandomBiasField(p=0.25),
        ])
        return augment

    def train_dataloader(self, *args, **kwargs):
        """
        Generates one or multiple Pytorch DataLoaders for train.

        Returns
        -------
        _ : Collection of DataLoader
            Collection of train dataloaders specifying training samples.
        """
        return super().train_dataloader(num_workers=0, shuffle=False)

    def val_dataloader(self, *args, **kwargs):
        """
        Generates one or multiple Pytorch DataLoaders for validation.

        Returns
        -------
        _ : Collection of DataLoader
            Collection of validation dataloaders specifying validation samples.
        """
        return super().val_dataloader(num_workers=0, shuffle=False)

    def add_sampling_map(
        self,
        subjects: List[tio.Subject],
        image_reference: str = '3T_MPR',
    ) -> List[tio.Subject]:
        """
        Add sampling map to list of subjects.

        Parameters
        ----------
        subjects : List[tio.Subject]
            List of tio.Subject instances.
        image_reference : str, Optional
            Name of the image to base the sampling map.
            Default = ``"3T_MPR"```.

        Returns
        -------
        new_subjects : List[tio.Subject]
            List of tio.Subject instances with added sampling map.
        """
        new_subjects = []
        for subject in subjects:
            probabilities = create_probability_map(subject, self.patch_size)
            sampling_map = tio.Image(tensor=probabilities,
                                     affine=subject[image_reference].affine,
                                     type=tio.SAMPLING_MAP)
            subject.add_image(sampling_map, 'sampling_map')
            new_subjects.append(subject)
        return new_subjects

    def save(self,
             dataloader: DataLoader,
             root: PathType = Path(
                 "/media/cerebro/Workspaces/Students/Eduardo_Diniz/Studies"),
             subj_dir: str = 'radio_3T_MPR_png/unprocessed',
             data_dir: str = '',
             fold: str = "train") -> None:
        """
        Arguments
        ---------
        root : Path or str, optional
            Root where to save data. Default = ``'~/LocalCerebro'``.
        """
        save_root = ensure_exists(
            Path(root).expanduser() / self.study / subj_dir / fold / data_dir)

        image_name2modality = {
            "3T_MPR": "T1w_MPR1",
            "3T_SPC": "T2w_SPC1",
            "3T_FLR": "T2w_FLR1",
        }
        _, plt = import_mpl_plt()

        for batch in dataloader:
            subjects = get_subjects_from_batch(cast(Dict[str, Any], batch))
            for subject in subjects:
                subj_id = subject["subj_id"]
                field = subject["field"]
                for image_name in subject.get_images_names():
                    if image_name not in ['sampling_map']:
                        filename = self.png_template_radio.substitute(
                            subj_id=subj_id,
                            field=field,
                            modality=image_name2modality[image_name])
                        image = subject[image_name]
                        data = image.data[-1].numpy()
                        img_slice = rotate(data[:, :, 0], radiological=True)
                        img_slice = ((img_slice * 127.5) + 127.5).astype(
                            np.uint8)
                        # img_slice = img_slice.astype(np.uint8)

                        plt.imsave(
                            str(save_root / Path(filename).name),
                            img_slice,
                            cmap='gray',
                        )
